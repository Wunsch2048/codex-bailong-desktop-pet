"""Verify bundled Python code matches the reviewed sources, ignoring file paths."""
import ast,hashlib,json,types
from pathlib import Path
from PyInstaller.archive.readers import ZlibArchiveReader
ROOT=Path(__file__).resolve().parent
def signature(code):
    def constant(value):
        if isinstance(value,types.CodeType):return signature(value)
        if isinstance(value,frozenset):return ('frozenset',tuple(sorted(repr(v) for v in value)))
        return repr(value)
    return (code.co_code.hex(),code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,code.co_flags,tuple(constant(c) for c in code.co_consts))
def check():
    archive=ZlibArchiveReader(str(ROOT/'build/BailongEnhanced/PYZ-00.pyz'))
    result={}
    for name in ('cli_launch_health','process_launch','startup_probe','drag_panel','project_cost_drain','index_maintenance'):
        source=compile((ROOT/'app'/f'{name}.py').read_text(encoding='utf-8'),name+'.py','exec')
        result[name]=signature(source)==signature(archive.extract(name))
    for name in ('project_cost','project_cost_store','project_membership','project_cost_ui','stable_tray','hover_hints','native_landing','tray_history','silent_notify','storage_locations','program_location','wsl_codex','animation_updates','chat_protocol','chat_config','chat_transport','chat_probe','data_page_motion','material_removal','settings_controls','choice_controls','number_controls','quota_history','quota_workload','quota_compare_ui','week_cycle'):
        source=compile((ROOT/'app'/f'{name}.py').read_text(encoding='utf-8-sig'),name+'.py','exec')
        result[name]=signature(source)==signature(archive.extract(name))
    for name in ('edge_dock','locomotion','installation_cleanup','reset_presentation','reset_card','quick_actions','codex_startup','decode_runtime','program_updates','program_update_apply','material_probe','material_store','material_controller','card_surface_probe','linked_report_motion','sustained_probe','continuous_work','sustained_player','sustained_assets','native_coordinates','interaction_probe'):
        source=compile((ROOT/'app'/f'{name}.py').read_text(encoding='utf-8'),name+'.py','exec')
        result[name]=signature(source)==signature(archive.extract(name))
    for name in ('settings_presentation','theme_registry','theme_catalog','theme_runtime','theme_controls','windows_entries','app_updates','update_controller','update_widgets','firefox_video','video_fullscreen','video_yield','installer','shared_assets','optional_tools','activity_targets','log_catalog','completion_ledger','deployment_state','performance_metrics','desktop','quota','desktop_core','desktop_services','desktop_settings','settings_draft','inline_confirmation','chat_window','stream_player','status_reactions','enhanced','pet','version','selftest','enhanced_core','reset_watch','compact_bubble','dashboard_cards','token_calendar','token_charts','ring_metrics','ring_widgets','typography','detail_sections','panel_transition','surface_morph','card_motion','spring_motion','loop_cache','status_motion','status_paint','status_indicator','refresh_indicator','refresh_flow','token_analytics','daily_report','island_widgets','ui_theme','chart_reveal','chart_curve','codex_navigation','codex_connection','connection_health','connection_widgets','conversation_roster','session_read_state','codex_live_status','book_reference','quota_summary','quota_summary_data'):
        source=compile((ROOT/'app'/f'{name}.py').read_text(encoding='utf-8'),name+'.py','exec')
        result[name]=signature(source)==signature(archive.extract(name))
    print(json.dumps(result,indent=2))
    return all(result.values())
if __name__=='__main__':raise SystemExit(0 if check() else 1)
