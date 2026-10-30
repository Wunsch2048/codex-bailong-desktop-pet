"""Source CI without optional multi-GB artwork; isolate Qt and user settings.

The release runner additionally binds source, compiled modules and actual assets.
Hosted Windows may disable desktop animation, so animation tests use an explicit
enabled system-policy fixture; performance/reduced-motion cases can override it.
"""
import concurrent.futures,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODULES='''test_storage_locations test_token_calendar test_material_store test_quota_compare_ui test_wsl_codex test_animation_updates test_quota_history test_daily_report test_quota_summary_data test_spring_motion test_status_reactions.SchedulerTests test_ring_metrics test_work_actions test_sustained_reactions test_soft_curves_navigation test_release_version test_app_updates test_loop_cache test_decoder_runtime test_animation_quality test_sustained_player test_program_updates test_status_indicator test_read_completion test_reset_card test_reset_presentation test_reset_watch test_reset_recovery test_audit_fixes test_chat_config test_chat_config_ui test_chat_transport test_typography test_liquid_status test_release_retention test_local_workflow test_tray_history test_tray_quota test_native_landing test_hover_hints test_shared_card_transition test_status_handoff test_decode_geometry test_shortcuts_startup test_entry_icon test_token_rate test_rate_floor test_rate_integration test_live_rate test_quota_workload test_project_cost test_project_cost_reliability test_project_cost_drain test_index_maintenance test_material_incremental test_stable_tray test_process_launch test_upgrade_settings test_presentation_policy'''.split()
def run(module):
 with tempfile.TemporaryDirectory(prefix='bailong-source-ci-') as folder:
  env=dict(os.environ,LOCALAPPDATA=folder,APPDATA=str(Path(folder)/'roaming'),CODEX_HOME=str(Path(folder)/'codex'),BAILONG_ISOLATED='1',QT_QPA_PLATFORM='offscreen',PYTHONIOENCODING='utf-8',PYTHONPATH=str(ROOT/'app')+os.pathsep+str(ROOT))
  code="import faulthandler,unittest;from unittest.mock import patch;faulthandler.dump_traceback_later(65);fixture=patch('settings_controls._system_motion_enabled',return_value=True);fixture.start();unittest.main(module=None,defaultTest="+repr(module)+",verbosity=2)"
  started=time.monotonic()
  try:
   done=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True,timeout=75)
   result=dict(module=module,returncode=done.returncode,seconds=round(time.monotonic()-started,2))
   if done.returncode:result['failure']=(done.stdout+done.stderr).decode('utf-8',errors='replace')[-6000:]
  except subprocess.TimeoutExpired:result=dict(module=module,returncode='timeout')
  return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,MODULES))
 for item in results:print(json.dumps(item,ensure_ascii=True),flush=True)
 failed=[x['module'] for x in results if x['returncode']!=0]
 print(json.dumps(dict(sourceModules=len(results),failed=failed,optionalArtwork=False,fullReleaseAcceptance=False)))
 raise SystemExit(1 if failed else 0)
