"""API USD isolation, historic accounting and compact pricing navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
from PySide6.QtWidgets import QApplication,QWidget,QPushButton
from PySide6.QtCore import QEvent
from official_api_prices import ApiPriceCache,OfficialApiPrices,parse_document,PriceBook,DOCUMENT
from test_official_credit_rates import Network,Reply,DOC as CREDIT_DOC

APP=QApplication.instance() or QApplication([])
DOC=b'''# Pricing
Prices per 1M tokens.
### Standard pricing data
| Model | Short context input | Short context output | Short context cached input | Short context 30m write | Short context 12h write | Long context input | Long context output | Long context cached input | Long context 30m write | Long context 12h write |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6.1-sol | $2.00 | $10.00 | $0.10 | $2.50 | $5.00 | $4.00 | $15.00 | $0.20 | $5.00 | $10.00 |
| gpt-5.5-pro (<272K context length) | $30.00 | $180.00 | - | - | - | $60.00 | $270.00 | - | - | - |

| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-4.1 | $2.00 | $8.00 | $0.50 |
### Fast pricing data
| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-6.1-sol | $999 | $999 | $999 |
'''

class ApiPricesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.file=self.root/'api.json';self.now=1800000000.;self.network=Network();self.network.next=Reply(DOC,url=DOCUMENT)
        self.service=OfficialApiPrices(self.file,clock=lambda:self.now,network=self.network)
        self.addCleanup(self.service.close);self.addCleanup(self.service.deleteLater)
        self.path_patch=patch('official_api_prices.cache_path',return_value=self.file);self.path_patch.start();self.addCleanup(self.path_patch.stop)
        self.prefs_patch=patch('cost_preferences.path',return_value=self.root/'prefs.json');self.prefs_patch.start();self.addCleanup(self.prefs_patch.stop)
    def test_only_standard_short_context_usd_is_selected(self):
        rates=parse_document(DOC)
        self.assertEqual(rates['gpt-6.1-sol']['rates'],[2,.1,10])
        self.assertEqual(rates['gpt-5.5-pro']['rates'],[30,None,180])
        self.assertEqual(len(rates),3)
        with self.assertRaises(ValueError):parse_document(CREDIT_DOC)
        for raw in [DOC.replace(b'Standard pricing data',b'Batch pricing data'),DOC.replace(b'$2.00',b'2 credits',1),
                    DOC.replace(b'Short context input',b'Long context input',1),DOC.replace(b'$0.10',b'$999',1)]:
            with self.assertRaises(ValueError):parse_document(raw)
    def test_api_and_credit_caches_cannot_be_interchanged(self):
        from official_credit_rates import RateCache,parse_document as credits
        cache=RateCache(self.file);cache.accept(credits(CREDIT_DOC),self.now)
        self.assertTrue(ApiPriceCache(self.file).invalid)
        self.service.cache.accept(parse_document(DOC),self.now)
        self.assertTrue(RateCache(self.file).invalid)
    def test_live_controller_updates_separate_api_cache(self):
        self.service.request();self.network.next.finished.emit()
        self.assertFalse(self.service.cache.error);self.assertEqual(self.service.cache.data['unit'],'usd_per_million_tokens')
        self.assertEqual(self.service.cache.data['context'],'short')
        self.assertEqual(ApiPriceCache(self.file).data,self.service.cache.data)
    def test_user_overrides_and_unknown_cache_price_are_preserved(self):
        from cost_preferences import defaults,prices,price_history
        self.service.cache.accept(parse_document(DOC),self.now)
        value=defaults();value['prices']={'gpt-6.1-sol':[0,0,0],'custom':[3,1,5],'gpt-4.1':[None,None,None]}
        result=prices(value)
        self.assertEqual(result['gpt-6.1-sol'],(0,0,0));self.assertEqual(result['custom'],(3,1,5))
        self.assertNotIn('gpt-4.1',result);self.assertNotIn('gpt-5.5-pro',result)
        book=PriceBook(price_history(value))
        self.assertEqual(book.rate('gpt-6.1-sol',self.now+1),(0,0,0));self.assertIsNone(book.rate('gpt-4.1',self.now+1))
    def test_new_prices_apply_from_observation_without_rewriting_past(self):
        from official_api_prices import price_history
        from project_cost import RATES,pricing_revision
        self.service.cache.accept(parse_document(DOC),self.now)
        newer=parse_document(DOC);newer['gpt-6.1-sol']['rates']=[4,.2,20]
        self.service.cache.accept(newer,self.now+100)
        history=price_history({},RATES);book=PriceBook(history)
        self.assertEqual(book.rate('gpt-6.1-sol',self.now-1),(2,.1,10))
        self.assertEqual(book.rate('gpt-6.1-sol',self.now+99),(2,.1,10))
        self.assertEqual(book.rate('gpt-6.1-sol-2026-10-01',self.now+100),(4,.2,20))
        self.assertIsNone(book.rate('gpt-4.1',self.now-1));self.assertEqual(book.rate('gpt-4.1',self.now),(2,.5,8))
        self.assertIsNone(book.rate('unknown',self.now+100))
        before=pricing_revision(RATES,history);self.service.cache.accept(newer,self.now+150)
        self.assertEqual(before,pricing_revision(RATES,price_history({},RATES)))
        with self.assertRaises(ValueError):self.service.cache.accept(parse_document(DOC),self.now-1)
        with patch.dict(RATES,{'gpt-6.1-sol':(99,99,99)}):
            self.assertEqual(PriceBook(price_history({},RATES)).rate('gpt-6.1-sol',self.now-1),(2,.1,10))
    def test_summary_details_and_json_roundtrip_use_same_history_within_one_day(self):
        from test_cost_extension import fixture
        from project_cost import snapshot
        from cost_details import detail_snapshot
        dbpath,original=fixture(self.root)
        with closing(sqlite3.connect(dbpath)) as db:
            stamps=sorted(r[0] for r in db.execute('SELECT stamp FROM cost_revision_events'))
            raw_before=db.execute('SELECT * FROM cost_revision_events ORDER BY id').fetchall()
        self.assertEqual(len(stamps),2)
        rates=parse_document(DOC);rates['gpt-6.1-sol']['rates']=[4,.2,20]
        self.service.cache.accept(rates,sum(stamps)/2)
        with closing(sqlite3.connect(dbpath)) as db,db:data=snapshot(db,time.time(),{})
        project=data['ranges']['all'][0]
        self.assertAlmostEqual(project['cost'],.00341+.00682)
        data=json.loads(json.dumps(data));project=data['ranges']['all'][0]
        details=detail_snapshot(dbpath,project,price_table=data['price_table'],price_history=data['price_history'])
        self.assertAlmostEqual(details[0]['cost'],project['cost'])
        rates['gpt-6.1-sol']['rates']=[10,1,50];self.service.cache.accept(rates,time.time()+10)
        with closing(sqlite3.connect(dbpath)) as db,db:
            after=snapshot(db,time.time(),{})
            self.assertEqual(db.execute('SELECT * FROM cost_revision_events ORDER BY id').fetchall(),raw_before)
        self.assertAlmostEqual(after['ranges']['all'][0]['cost'],project['cost'])
    def test_compact_editor_keeps_manual_fields_in_secondary_page(self):
        from pricing_ui import PricingEditor
        from cost_preferences import load
        self.service.cache.accept(parse_document(DOC),self.now)
        host=QWidget();host.resize(246,430);host.show();editor=PricingEditor(host,price_service=self.service);APP.processEvents()
        try:
            self.assertEqual(editor.page,'home');self.assertFalse(editor.findChildren(QPushButton,'pricingModel'))
            self.assertEqual(editor.price_refresh.text(),'更新模型价格')
            editor.models_button.click();APP.processEvents();self.assertEqual(editor.page,'models')
            self.assertTrue(editor.model_rows);editor.search.setText('gpt-6.1-sol')
            editor.edit_model('gpt-6.1-sol');editor.price_fields[0].setText('0');editor.finish_model()
            self.assertEqual(editor.page,'models');self.assertEqual(editor.draft['prices']['gpt-6.1-sol'][0],0)
            editor.go_back();self.assertEqual(editor.page,'home');self.assertEqual(editor.draft['prices']['gpt-6.1-sol'][0],0)
            editor.commit_draft();self.assertEqual(load()['prices']['gpt-6.1-sol'][0],0)
        finally:host.close();host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_editor_price_refresh_does_not_save_or_overwrite_currency_draft(self):
        from pricing_ui import PricingEditor
        host=QWidget();host.resize(246,430);host.show();editor=PricingEditor(host,price_service=self.service)
        try:
            editor.currency.setCurrentIndex(editor.currency.findData('CNY'));editor.fx.setText('7.1')
            self.assertFalse(editor.fx_refresh.isHidden())
            editor.price_refresh.click();self.assertTrue(self.service.busy)
            self.network.next.finished.emit();self.assertEqual(editor.draft['currency'],'CNY');self.assertEqual(editor.draft['fx'],7.1)
            self.assertFalse((self.root/'prefs.json').exists())
            self.assertIn('上次检查',editor.price_status.text())
        finally:host.close();host.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)

if __name__=='__main__':unittest.main()
