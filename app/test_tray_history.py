"""Tray identity boundaries, atomic backup ordering and silent notification reuse."""
import io
import json
import struct
from contextlib import contextmanager
import unittest
from unittest.mock import Mock,patch
import tray_history as history
from silent_notify import SilentNotifier

OLD=r'C:\Programs\BailongEnhanced\versions\old\BailongEnhanced.exe'
NEW=r'C:\Programs\BailongEnhanced\versions\new\BailongEnhanced.exe'
OTHER=r'C:\Other\BailongEnhanced.exe'

def record(name,exe,uid=0,promoted=None):
    values=[['ExecutablePath',exe,1],['UID',uid,4],['IconSnapshot',{'base64':'YWJj'},3]]
    if promoted is not None:values.append(['IsPromoted',promoted,4])
    return dict(name=name,exe=exe,uid=uid,promoted=promoted,values=values)

class Registry:
    HKEY_CURRENT_USER='HKCU';KEY_READ=1;KEY_SET_VALUE=2;REG_DWORD=4;REG_BINARY=3
    def __init__(self,records,order=None):
        self.rows={r['name']:{n:(__import__('base64').b64decode(v['base64']) if isinstance(v,dict) else v,t)
                   for n,v,t in r['values']} for r in records};self.deleted=[]
        self.root={} if order is None else {history.ORDER:(order,self.REG_BINARY)}
    def OpenKey(self,root,path,*unused):
        if path==history.KEY:
            key=Mock();key.__enter__=Mock(return_value=self.root);key.__exit__=Mock(return_value=False);return key
        name=path.rsplit('\\',1)[-1]
        if name not in self.rows:raise FileNotFoundError(name)
        key=Mock();key.__enter__=Mock(return_value=name);key.__exit__=Mock(return_value=False);return key
    def QueryValueEx(self,key,name):
        values=key if isinstance(key,dict) else self.rows[key]
        if name not in values:raise FileNotFoundError(name)
        return values[name]
    def QueryInfoKey(self,key):return 0,len(self.rows[key]),0
    def EnumValue(self,key,index):
        n,(v,t)=list(self.rows[key].items())[index];return n,v,t
    def SetValueEx(self,key,n,unused,t,v):
        values=key if isinstance(key,dict) else self.rows[key];values[n]=(v,t)
    def DeleteKey(self,root,path):
        n=path.rsplit('\\',1)[-1];self.deleted.append(n);del self.rows[n]
    def CreateKey(self,root,path):
        self.rows.setdefault(path.rsplit('\\',1)[-1],{})
        return self.OpenKey(root,path)

def order(*ids):return struct.pack('<'+'Q'*len(ids),*ids)

@contextmanager
def backed_memory():
    raw=io.BytesIO();stream=Mock();stream.write.side_effect=raw.write;stream.fileno.return_value=1
    handle=Mock();handle.__enter__=Mock(return_value=stream);handle.__exit__=Mock(return_value=False)
    with patch.object(history.Path,'mkdir'),patch.object(history.Path,'open',return_value=handle),\
         patch.object(history.Path,'read_bytes',side_effect=raw.getvalue),patch.object(history.os,'fsync'):
        yield raw

class TrayHistoryTests(unittest.TestCase):
    def test_guid_owner_without_uid_is_verified_before_migration(self):
        fixed=record('9',r'C:\Programs\BailongEnhanced\tray\BailongTray.exe',uid=None)
        fixed['values']=[v for v in fixed['values'] if v[0]!='UID']+[['IconGuid','{6BAEA166-D3D9-4FFB-88C4-39A669A20E69}',1]]
        old=record('2',OLD,promoted=1);reg=Registry([fixed,old])
        approved=dict(keep=fixed,remove=[old],promoted=1,retired=[],inheritPin=False)
        with backed_memory():result=history.apply_plan(reg,approved,'backup.json')
        self.assertEqual(result['removed'],['2']);self.assertEqual(reg.rows['9']['IsPromoted'],(1,4))
        reg.rows['9']['IconGuid']=('{different}',1)
        self.assertFalse(history._same_record(reg,fixed))
    def test_only_exact_owned_paths_and_known_uids_are_candidates(self):
        rows=[record('1',NEW),record('2',OLD),record('3',OLD,history.LEGACY_UID),
              record('4',OTHER),record('5',OLD,321)]
        result=history.plan(rows,[OLD,NEW],NEW)
        self.assertEqual([r['name'] for r in result['remove']],['2','3'])
    def test_active_old_process_is_preserved(self):
        rows=[record('1',NEW),record('2',OLD),record('3',OLD,history.LEGACY_UID)]
        self.assertEqual(history.plan(rows,[OLD,NEW],NEW,[OLD])['remove'],[])
    def test_current_legacy_hidden_icon_can_be_retired(self):
        rows=[record('1',NEW),record('2',NEW,history.LEGACY_UID)]
        self.assertEqual([r['name'] for r in history.plan(rows,[NEW],NEW,[NEW])['remove']],['2'])
    def test_current_registration_must_be_unique_and_present(self):
        self.assertIsNone(history.plan([record('1',OLD)],[OLD,NEW],NEW))
        self.assertIsNone(history.plan([record('1',NEW),record('2',NEW)],[NEW],NEW))
        self.assertIsNone(history.plan([record('1',NEW)],[OLD],NEW))
    def test_migrates_previous_visibility_without_overwriting_current_choice(self):
        rows=[record('1',NEW),record('2',OLD,promoted=1)]
        self.assertEqual(history.plan(rows,[OLD,NEW],NEW,preferred=OLD)['promoted'],1)
        rows[0]=record('1',NEW,promoted=0)
        self.assertEqual(history.plan(rows,[OLD,NEW],NEW,preferred=OLD)['promoted'],0)
    def test_first_deployment_can_inherit_pin_from_exact_predecessor(self):
        rows=[record('1',NEW,promoted=0),record('2',OLD,promoted=1)]
        result=history.plan(rows,[OLD,NEW],NEW,preferred=OLD,inherit_previous=True)
        self.assertEqual(result['promoted'],1);self.assertTrue(result['inheritPin'])
        reg=Registry(rows)
        with backed_memory():history.apply_plan(reg,result,'backup.json')
        self.assertEqual(reg.rows['1']['IsPromoted'],(1,4))
        self.assertFalse(history.plan(rows,[OLD,NEW],NEW,preferred=OLD)['inheritPin'])
    def test_unrelated_old_pin_does_not_promote_a_new_version(self):
        rows=[record('1',NEW,promoted=0),record('2',OLD,promoted=0),record('3',OTHER,promoted=1)]
        result=history.plan(rows,[OLD,NEW,OTHER],NEW,preferred=OLD,inherit_previous=True)
        self.assertEqual(result['promoted'],0);self.assertFalse(result['inheritPin'])
    def test_concurrent_current_preference_change_is_not_overwritten(self):
        rows=[record('1',NEW,promoted=0),record('2',OLD,promoted=1)]
        result=history.plan(rows,[OLD,NEW],NEW,preferred=OLD,inherit_previous=True)
        reg=Registry(rows);reg.rows['1']['IsPromoted']=(1,4)
        writes=[];original=reg.SetValueEx
        def set_value(*args):writes.append(args);return original(*args)
        reg.SetValueEx=set_value
        with backed_memory():history.apply_plan(reg,result,'backup.json')
        self.assertFalse(writes)
    def test_backup_failure_prevents_all_registry_mutations(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows)
        with patch.object(history.Path,'mkdir'),patch.object(history.Path,'open',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        self.assertEqual(reg.deleted,[])
    def test_backup_covers_exact_raw_values_and_cleanup_preserves_unrelated(self):
        rows=[record('1',NEW),record('2',OLD,promoted=1),record('3',OTHER)];reg=Registry(rows)
        raw=io.BytesIO();stream=Mock();stream.write.side_effect=raw.write;stream.fileno.return_value=1
        handle=Mock();handle.__enter__=Mock(return_value=stream);handle.__exit__=Mock(return_value=False)
        with patch.object(history.Path,'mkdir'),patch.object(history.Path,'open',return_value=handle),\
             patch.object(history.Path,'read_bytes',side_effect=raw.getvalue),patch.object(history.os,'fsync'):
            result=history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        self.assertEqual(result['removed'],['2']);self.assertIn('3',reg.rows)
        self.assertEqual(reg.rows['1']['IsPromoted'],(1,4))
        self.assertIn('YWJj',raw.getvalue().decode())
    def test_changed_record_is_skipped(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows);approved=history.plan(rows,[OLD,NEW],NEW)
        reg.rows['2']['IsPromoted']=(1,4)
        raw=io.BytesIO();stream=Mock();stream.write.side_effect=raw.write;stream.fileno.return_value=1
        handle=Mock();handle.__enter__=Mock(return_value=stream);handle.__exit__=Mock(return_value=False)
        with patch.object(history.Path,'mkdir'),patch.object(history.Path,'open',return_value=handle),\
             patch.object(history.Path,'read_bytes',side_effect=raw.getvalue),patch.object(history.os,'fsync'):
            result=history.apply_plan(reg,approved,'backup.json')
        self.assertEqual(result['removed'],[]);self.assertEqual(result['skipped'],['2'])
    def test_cleanup_also_removes_only_retired_order_ids_and_backs_up_original(self):
        rows=[record('1',NEW),record('2',OLD),record('3',OTHER)]
        original=order(3,2,1,99);reg=Registry(rows,original)
        with backed_memory() as raw:result=history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        self.assertEqual(reg.root[history.ORDER],(order(3,1,99),3))
        self.assertTrue(result['orderChanged']);self.assertFalse(result['orderSkipped'])
        self.assertEqual(__import__('base64').b64decode(json.loads(raw.getvalue())['order']),original)
        self.assertEqual(reg.rows['3']['ExecutablePath'][0],OTHER)
    def test_record_changed_during_cleanup_keeps_its_order_entry(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows,order(2,1))
        approved=history.plan(rows,[OLD,NEW],NEW);reg.rows['2']['IsPromoted']=(1,4)
        with backed_memory():result=history.apply_plan(reg,approved,'backup.json')
        self.assertEqual(reg.root[history.ORDER][0],order(2,1));self.assertFalse(result['orderChanged'])
    def test_unknown_order_format_prevents_any_cleanup(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows,b'bad')
        with self.assertRaises(ValueError):history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'unused')
        self.assertEqual(reg.deleted,[])
    def test_user_reorder_after_backup_prevents_cleanup(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows,order(2,1))
        with backed_memory(),patch.object(history,'_same_record',side_effect=lambda *_:reg.root.update({history.ORDER:(order(1,2),3)}) or True):
            with self.assertRaises(OSError):history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        self.assertEqual(reg.deleted,[]);self.assertEqual(reg.root[history.ORDER][0],order(1,2))
    def test_late_user_reorder_is_never_overwritten(self):
        rows=[record('1',NEW),record('2',OLD)];reg=Registry(rows,order(2,1))
        delete=reg.DeleteKey
        def changed(*args):delete(*args);reg.root[history.ORDER]=(order(1,2,99),3)
        with backed_memory(),patch.object(reg,'DeleteKey',side_effect=changed):
            result=history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        self.assertTrue(result['orderSkipped']);self.assertEqual(reg.root[history.ORDER][0],order(1,2,99))
    def test_prior_retired_ids_repair_order_without_deleting_any_current_records(self):
        rows=[record('1',NEW),record('3',OTHER)];reg=Registry(rows,order(3,2,1,99))
        approved=history.plan(rows,[OLD,NEW],NEW,retired=['2','3','unknown'])
        self.assertEqual(approved['retired'],['2'])
        with backed_memory():result=history.apply_plan(reg,approved,'backup.json')
        self.assertEqual(result['removed'],[]);self.assertEqual(reg.root[history.ORDER][0],order(3,1,99))
    def test_retired_id_recreated_during_backup_keeps_its_order_entry(self):
        rows=[record('1',NEW)];reg=Registry(rows,order(2,1));approved=history.plan(rows,[OLD,NEW],NEW,retired=['2'])
        def recreated(*args):reg.rows['2']={'ExecutablePath':(OTHER,1),'UID':(0,4)};return True
        with backed_memory(),patch.object(history,'_same_record',side_effect=recreated):
            result=history.apply_plan(reg,approved,'backup.json')
        self.assertFalse(result['orderChanged']);self.assertEqual(reg.root[history.ORDER][0],order(2,1))
    def test_backup_recovery_accepts_only_exact_owned_paths_and_consistent_raw_identity(self):
        rows=[record('2',OLD),record('3',OTHER),record('4',OLD)]
        rows[2]['values'][0][1]=OTHER
        file=Mock();file.name='backup.json';file.stat.return_value.st_size=200
        file.read_text.return_value=json.dumps(dict(schema=1,registry=history.KEY,plan=dict(remove=rows)))
        with patch.object(history.Path,'is_dir',return_value=True),patch.object(history.Path,'glob',return_value=[file]):
            self.assertEqual(history.retired_from_backups('unused',[OLD,NEW],{'2','3','4'}),{'2'})
    def test_explicit_rollback_restores_identity_and_retains_later_user_order(self):
        rows=[record('1',NEW),record('2',OLD),record('3',OTHER)];reg=Registry(rows,order(3,2,1))
        with backed_memory() as raw:history.apply_plan(reg,history.plan(rows,[OLD,NEW],NEW),'backup.json')
        reg.root[history.ORDER]=(order(1,3,99),3)
        with patch.object(history.Path,'read_text',return_value=raw.getvalue().decode()):
            self.assertEqual(history.restore_backup(reg,'backup.json'),['2'])
        self.assertEqual(reg.rows['2']['ExecutablePath'],(OLD,1))
        self.assertEqual(reg.root[history.ORDER][0],order(1,3,99,2))
    def test_isolated_runs_never_reconcile_real_shell(self):
        with patch.dict(history.os.environ,BAILONG_ISOLATED='1'),patch.object(history,'snapshot') as read:
            history.reconcile('unused');read.assert_not_called()
    def test_silent_notification_only_modifies_main_tray_and_never_deletes_it(self):
        shell=Mock()
        with patch('silent_notify.ctypes.WinDLL',return_value=shell),patch('silent_notify.qt_tray_window',return_value=1234),\
             patch.dict(history.os.environ,BAILONG_ISOLATED='0'):
            notifier=SilentNotifier();self.assertTrue(notifier.show('完成','查看回复'));notifier.close()
        shell.Shell_NotifyIconW.assert_called_once()
        self.assertEqual(shell.Shell_NotifyIconW.call_args.args[0],1)
        self.assertEqual(notifier.data.hWnd,1234);self.assertEqual(notifier.data.uID,0)
        self.assertTrue(notifier.data.dwInfoFlags&0x10)
    def test_missing_main_tray_has_no_hidden_or_audible_fallback(self):
        shell=Mock()
        with patch('silent_notify.ctypes.WinDLL',return_value=shell),patch('silent_notify.qt_tray_window',return_value=None),\
             patch.dict(history.os.environ,BAILONG_ISOLATED='0'):
            self.assertFalse(SilentNotifier().show('完成','查看回复'))
        shell.Shell_NotifyIconW.assert_not_called()

if __name__=='__main__':unittest.main()
