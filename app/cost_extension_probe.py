"""Isolated frozen entry check for the new cost/rate routes and Qt TLS."""
def run(output):
    import json,tempfile,time
    from pathlib import Path
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtCore import QEventLoop,QTimer,QUrl,QEvent,QPointF,Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtNetwork import QSslSocket,QNetworkAccessManager,QNetworkRequest
    import cost_preferences as prefs
    from pricing_ui import PricingEditor
    from live_rate_ui import LiveRateCard
    from public_status import shared,decode_status
    from cost_details import encode_export
    from project_cost_ui import ProjectCosts,SessionButton,TurnRow
    from turn_detail_cache import shared as turn_cache
    from version import VERSION
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    from typography import install_ui_font
    install_ui_font(app);old_path=prefs.path;old_cache=prefs._cached;service=shared();original=service.request
    result=dict(version=VERSION,isolated=True,realSettingsChanged=False)
    try:
        with tempfile.TemporaryDirectory(prefix='bailong-cost-probe-') as folder:
            prefs.path=lambda:Path(folder)/'pricing.json';prefs._cached=None
            from official_api_prices import OfficialApiPrices,PriceBook
            from official_credit_rates import OfficialCreditRates
            from official_rates_ui import OfficialRatesPage
            rates={name:dict(name=name,rates=[2.,.1,10.]) for name in ('gpt-6.1-sol','gpt-6-astra','gpt-6-luna')}
            api=OfficialApiPrices(Path(folder)/'api.json');api.cache.accept(rates,time.time())
            credits=OfficialCreditRates(Path(folder)/'credits.json');credits.cache.accept(rates,time.time())
            result['separateOfficialUnits']=api.cache.data['unit']=='usd_per_million_tokens' and credits.cache.data['unit']=='credits_per_million_tokens'
            result['priceHistory']=PriceBook(dict(manual={},builtin={'gpt-6.1-sol':[1.,.05,5.]},versions=api.cache.data['versions'])).rate('gpt-6.1-sol',0)==(1.,.05,5.)
            host=QWidget();host.resize(240,400);host.show();editor=PricingEditor(host,['missing-model'],price_service=api)
            result['compactPricingHome']=editor.page=='home' and hasattr(editor,'price_refresh') and not editor.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton,'pricingModel')
            editor.models_button.click();editor.show_price_history();app.processEvents()
            result['officialApiPage']=editor.history_page.isVisible() and editor.history_page.geometry()==editor.rect()
            editor.history_page.close();editor.edit_model('missing-model');editor.price_fields[0].setText('0');editor.price_fields[1].setText('0');editor.price_fields[2].setText('0');editor.finish_model();editor.commit_draft()
            page=OfficialRatesPage(host,credits);app.processEvents();result['officialCreditsPage']=page.isVisible() and page.geometry()==host.rect();page.close();api.close();credits.close()
            result['pricingSaved']=prefs.prices()['missing-model']==(0,0,0)
            raw=encode_export([dict(project='sample',period='all',model='m',tokens=1,usd_cost=0,unpriced_tokens=0)],'CSV');result['csvExport']=raw.startswith(b'\xef\xbb\xbf') and b'sample' in raw
            session=dict(id='s',name='长会话标题\n附件说明 '+('示例文字'*60),tokens=1000,cost=1.,detail_revision='sample')
            project=dict(id='p',name='示例项目',path='D:/sample',tokens=1000,cost=1.,parts=[.4,.3,.3],pending_tokens=0,sessions=1,session_ids=['s'],session_usage=[session],models=[],model_usage=[],archived=False)
            costs=ProjectCosts();costs.resize(250,360);costs.set_data(dict(ranges={'all':[project]}),'all');costs.show();costs.select(project);app.processEvents()
            result['costSummaryReuse']=costs.session_rows==[session] and costs.detail_job is None
            row=costs.findChild(SessionButton);result['boundedSessionRow']=row is not None and row.height()==57 and '\n' not in row.title
            turn=dict(id='t',stamp=time.time(),models=['sample-model'],tokens=1000,input=800,cached=100,output=200,cost=.01,pending_tokens=0,known=True,unknown=False)
            costs.open_session(dict(session,turns=[turn]));app.processEvents();part=costs.findChild(TurnRow);result['inlineTurnParts']=part is not None and part.token_parts==[700,100,200];costs.close()
            key=('isolated-probe','s','all','price',1,'a');turn_cache().finish(key,[dict(id='s',turns=[turn])]);old,exact=turn_cache().lookup(('isolated-probe','s','all','price',2,'b'));result['retainedTurnCache']=old==[turn] and not exact
            service.request=lambda:None;card=LiveRateCard(dict(rate=46.1,details=[dict(name='a',rate=31.8),dict(name='b',rate=14.3)]));card.setGeometry(300,400,121,20);card.show();card.popup.inspect(card.value,card);card.popup.animation.setCurrentTime(160);app.processEvents();result['compactBubble']=card.popup.width()==294 and card.popup.height()==140
            click=QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(card.rect().center()),QPointF(card.mapToGlobal(card.rect().center())),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
            app.sendEvent(card,click);app.processEvents();result['serviceDetails']=not card.service_panel.doc.isEmpty();result['directServiceEntry']=card.service_panel.page=='service' and card.service_panel.isVisible() and not card.popup.isVisible()
            app.sendEvent(card.service_panel,QEvent(QEvent.Type.WindowDeactivate));result['outsideClosesService']=not card.service_panel.isVisible();card.close();host.close()
            result['qtSsl']=QSslSocket.supportsSsl()
            # Public read-only endpoints; no login or paid inference endpoint.
            network=QNetworkAccessManager();loop=QEventLoop();pending=[];responses={}
            for key,url in [('status','https://status.openai.com/api/v2/summary.json'),('fx','https://api.frankfurter.dev/v2/rate/USD/CNY')]:
                request=QNetworkRequest(QUrl(url));request.setTransferTimeout(7000);reply=network.get(request);pending.append(reply)
                def done(k=key,r=reply):
                    try:
                        value=json.loads(bytes(r.readAll()))
                        responses[k]=dict(received=True,valid=bool(decode_status(value)) if k=='status' else isinstance(value.get('rate'),(int,float)),date=value.get('date'))
                    except Exception:responses[k]=dict(received=False,error=r.errorString())
                    if len(responses)==2:loop.quit()
                reply.finished.connect(done)
            QTimer.singleShot(8500,loop.quit);loop.exec();result['publicReads']=responses
            for reply in pending:
                if not reply.isFinished():reply.abort()
                reply.deleteLater()
        result['passed']=all(result.get(k) is True for k in ('pricingSaved','separateOfficialUnits','priceHistory','compactPricingHome','officialApiPage','officialCreditsPage','csvExport','costSummaryReuse','boundedSessionRow','inlineTurnParts','retainedTurnCache','compactBubble','serviceDetails','directServiceEntry','outsideClosesService','qtSsl'))
    except Exception as error:result.update(passed=False,error=repr(error))
    finally:prefs.path=old_path;prefs._cached=old_cache;service.request=original
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return 0 if result['passed'] else 1
