"""Public document validation, retained price history and bounded refresh."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QObject,Signal,QUrl,QByteArray,QEvent
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication,QWidget,QScrollArea
from official_credit_rates import parse_document,RateCache,OfficialCreditRates,DOCUMENT,DAY,MAX_BYTES

APP=QApplication.instance() or QApplication([])
DOC=b'''#### Token rates
The rates below are for Standard speed. Credit prices alone don't determine included subscription usage.
<table><thead><tr><th>Credits per 1M tokens</th><th>Input Tokens</th><th>Cached input tokens</th><th>Output Tokens</th></tr></thead>
<tbody><tr><td>GPT-6 Astra</td><td>250 credits</td><td>25 credits</td><td>1,250 credits</td></tr>
<tr><td>GPT-6.1 Sol</td><td>50 credits</td><td>2.5 credits</td><td>250 credits</td></tr>
<tr><td>GPT-6.1 Terra</td><td>25 credits</td><td>1.25 credits</td><td>125 credits</td></tr></tbody>
<tfoot><tr><td colspan="4">A note with 9 credits is not a model price.</td></tr></tfoot></table>
### Next section
'''

class Reply(QObject):
    readyRead=Signal();finished=Signal()
    def __init__(self,raw=DOC,error=False,url=DOCUMENT):
        super().__init__();self.raw=raw;self.failed=error;self.address=url;self.aborted=False
    def error(self):return QNetworkReply.NetworkError.ConnectionRefusedError if self.failed else QNetworkReply.NetworkError.NoError
    def url(self):return QUrl(self.address)
    def bytesAvailable(self):return len(self.raw)
    def readAll(self):return QByteArray(self.raw)
    def abort(self):self.aborted=True;self.failed=True;self.finished.emit()

class Network:
    def __init__(self):self.next=Reply();self.calls=[]
    def get(self,request):self.calls.append(request);return self.next

class OfficialRatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'rates.json';self.now=1800000000.
        self.net=Network();self.controller=OfficialCreditRates(self.path,clock=lambda:self.now,network=self.net)
        self.addCleanup(self.controller.close);self.addCleanup(self.controller.deleteLater)
    def accept(self):self.controller.request();self.net.next.finished.emit()
    def test_parser_uses_only_typed_standard_credit_table(self):
        rates=parse_document(DOC)
        self.assertEqual(len(rates),3);self.assertEqual(rates['gpt-6-astra']['rates'],[250,25,1250])
        self.assertEqual(rates['gpt-6.1-sol']['rates'],[50,2.5,250])
        self.assertEqual(len(parse_document(DOC.replace(b'GPT-6.1 Sol',b'<b>GPT-6.1 Sol</b>'))),3)
    def test_changed_scope_unit_column_duplicate_or_bad_number_is_rejected(self):
        for raw in [DOC.replace(b'Standard speed',b'Fast speed'),DOC.replace(b'included subscription usage',b'API usage'),
                    DOC.replace(b'Credits per 1M tokens',b'USD per 1M tokens'),DOC.replace(b'Cached input tokens',b'Output Tokens'),
                    DOC.replace(b'GPT-6.1 Sol',b'GPT-6 Astra'),DOC.replace(b'250 credits',b'NaN credits',1),
                    DOC.replace(b'250 credits',b'-1 credits',1),DOC.replace(b'2.5 credits',b'999 credits'),DOC+b'x'*MAX_BYTES]:
            with self.subTest(raw=raw[:45]):
                with self.assertRaises(ValueError):parse_document(raw)
    def test_changed_prices_keep_immutable_history_unchanged_checks_do_not_duplicate(self):
        cache=self.controller.cache;cache.accept(parse_document(DOC),self.now)
        first=copy.deepcopy(cache.data['versions'][0]);cache.accept(parse_document(DOC),self.now+10)
        self.assertEqual(len(cache.data['versions']),1);self.assertEqual(cache.data['checked_at'],self.now+10)
        new=parse_document(DOC.replace(b'50 credits',b'60 credits'))
        cache.accept(new,self.now+20)
        self.assertEqual(len(cache.data['versions']),2);self.assertEqual(cache.data['versions'][0],first)
        restored=RateCache(self.path);self.assertEqual(restored.data,cache.data)
        cache.accept(parse_document(DOC),self.now+30)
        self.assertEqual(len(cache.data['versions']),3)  # A real reversion is a new observation.
    def test_daily_automatic_check_manual_refresh_and_inflight_deduplication(self):
        self.controller.ensure_due();self.assertEqual(len(self.net.calls),1)
        self.controller.ensure_due();self.controller.request();self.assertEqual(len(self.net.calls),1)
        self.net.next.finished.emit();self.assertFalse(self.controller.busy)
        self.now+=DAY-1;self.controller.ensure_due();self.assertEqual(len(self.net.calls),1)
        self.net.next=Reply();self.controller.request();self.assertEqual(len(self.net.calls),2)
        self.net.next.finished.emit();self.now+=DAY
        self.net.next=Reply();self.controller.ensure_due();self.assertEqual(len(self.net.calls),3)
        self.assertEqual(self.net.calls[-1].url(),QUrl(DOCUMENT));self.assertEqual(self.net.calls[-1].transferTimeout(),10000)
    def test_network_parse_redirect_and_size_failures_keep_cached_prices(self):
        self.accept();first=copy.deepcopy(self.controller.cache.data['versions'])
        for reply in [Reply(error=True),Reply(raw=b'login page'),Reply(url='https://example.org/pricing.md'),Reply(raw=DOC+b'x'*MAX_BYTES)]:
            self.now+=31;self.net.next=reply;self.controller.request()
            if len(reply.raw)>MAX_BYTES:reply.readyRead.emit();self.assertTrue(reply.aborted)
            else:reply.finished.emit()
            self.assertEqual(self.controller.cache.data['versions'],first)
            self.assertTrue(self.controller.cache.error);self.assertFalse(self.controller.busy)
            self.assertFalse(self.controller.cache.due(self.now+DAY-1))
        self.assertEqual(RateCache(self.path).data['versions'],first)
    def test_disk_failure_does_not_publish_an_unsaved_new_price(self):
        self.accept();before=copy.deepcopy(self.controller.cache.data)
        self.now+=31;self.net.next=Reply(DOC.replace(b'50 credits',b'60 credits'));self.controller.request()
        with patch.object(self.controller.cache,'save',side_effect=OSError('disk full')):self.net.next.finished.emit()
        self.assertEqual(self.controller.cache.data,before);self.assertTrue(self.controller.cache.error)
        self.assertEqual(RateCache(self.path).data,before)
    def test_corrupt_cache_is_preserved_before_repair(self):
        self.path.write_bytes(b'broken original');cache=RateCache(self.path)
        self.assertTrue(cache.invalid);self.assertFalse(cache.data['versions'])
        cache.accept(parse_document(DOC),self.now)
        backups=list(self.path.parent.glob('rates.json.invalid-*'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),b'broken original')
        self.assertFalse(RateCache(self.path).invalid)
    def test_invalid_history_hash_or_wrong_units_are_not_used(self):
        self.accept();original=copy.deepcopy(self.controller.cache.data)
        for change in ('unit','price','time'):
            data=copy.deepcopy(original)
            if change=='unit':data['unit']='USD'
            elif change=='time':data['versions'][0]['observed_at']=True
            else:data['versions'][0]['rates']['gpt-6.1-sol']['rates'][0]=999
            self.path.write_text(json.dumps(data),encoding='utf-8')
            cache=RateCache(self.path);self.assertTrue(cache.invalid);self.assertFalse(cache.data['versions'])
    def test_shutdown_cancels_request_without_recording_a_failure(self):
        self.controller.request();self.controller.close()
        self.assertTrue(self.net.next.aborted);self.assertFalse(self.path.exists());self.assertIsNone(self.controller.reply)
    def test_rates_never_modify_api_price_defaults_or_unknown_model_fallback(self):
        from project_cost import RATES,rate
        before=copy.deepcopy(RATES);self.accept()
        self.assertEqual(RATES,before);self.assertIsNone(rate('unknown-model'))
    def test_ui_manual_refresh_history_scroll_and_reopen_reset(self):
        from official_rates_ui import OfficialRatesPage
        from theme_registry import current
        self.accept();self.controller.cache.accept(parse_document(DOC.replace(b'50 credits',b'60 credits')),self.now+1)
        host=QWidget();host.resize(246,400);host.show();page=OfficialRatesPage(host,self.controller);APP.processEvents()
        try:
            self.assertEqual(page.geometry(),host.rect());self.assertEqual(page.history.count(),2)
            self.assertIn('每天',page.status.text());self.assertIn('成功检查',page.check_time.text())
            page.history.setCurrentIndex(1);self.assertEqual(page.selected,0)
            self.assertEqual(page.rows_key[1],self.controller.cache.data['versions'][0]['revision'])
            before=page.rows_key;self.controller.changed.emit();self.assertEqual(page.rows_key,before)
            host.resize(268,430);APP.processEvents();self.assertEqual(page.geometry(),host.rect())
            self.assertEqual(page.area.verticalScrollBarPolicy(),Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page.area.verticalScrollBar().setValue(20);position=page.area.verticalScrollBar().value()
            self.controller.changed.emit();self.assertEqual(page.area.verticalScrollBar().value(),position)
            self.now+=31;self.net.next=Reply();page.refresh.click();self.assertTrue(self.controller.busy)
            self.net.next.finished.emit();self.assertTrue(page.refresh.isEnabled());self.assertEqual(page.selected,0)
            page.back.click();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            page=OfficialRatesPage(host,self.controller);self.assertIsNone(page.selected);self.assertEqual(page.area.verticalScrollBar().value(),0)
        finally:host.close();host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_quota_entry_uses_viewport_and_reuses_visible_page(self):
        from quota_compare_ui import QuotaCompareView
        import official_rates_ui
        area=QScrollArea();area.resize(268,420);view=QuotaCompareView();area.setWidget(view);area.setWidgetResizable(True);area.show();APP.processEvents()
        try:
            with patch.object(official_rates_ui,'shared',return_value=self.controller):
                view.rates_button.click();APP.processEvents()
                page=view.rates_page;self.assertIs(page.parentWidget(),area.viewport());self.assertEqual(page.geometry(),area.viewport().rect())
                view.rates_button.click();self.assertIs(view.rates_page,page)
                page.back.click();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        finally:area.close();area.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_background_new_price_preserves_reading_position(self):
        from official_rates_ui import OfficialRatesPage
        self.accept();host=QWidget();host.resize(246,300);host.show();page=OfficialRatesPage(host,self.controller);APP.processEvents()
        try:
            page.area.verticalScrollBar().setValue(20);before=page.area.verticalScrollBar().value();self.assertGreater(before,0)
            self.controller.cache.accept(parse_document(DOC.replace(b'50 credits',b'60 credits')),self.now+1)
            self.controller.changed.emit();APP.processEvents()
            self.assertEqual(page.area.verticalScrollBar().value(),before)
            page.history.setCurrentIndex(1);APP.processEvents();self.assertEqual(page.area.verticalScrollBar().value(),0)
        finally:host.close();host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

from PySide6.QtCore import Qt
if __name__=='__main__':unittest.main()
