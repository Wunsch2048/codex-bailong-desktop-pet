"""Follow-close policy checks without windows, real settings or process shutdown."""
import os,unittest,time
from types import SimpleNamespace
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from codex_startup import ExitGate
from desktop import DesktopPet

class ClosePolicyTests(unittest.TestCase):
    def pet(self):
        return SimpleNamespace(settings={'codex_exit':True},_codex_exit_gate=ExitGate(),_codex_polling=False,_codex_closing=False,close=Mock(),codexPresence=Mock())
    def deliver(self,pet,value,generation=None,wsl=False):
        if generation is None:generation=pet._codex_exit_gate.generation
        with patch('codex_connection.is_wsl_source',return_value=wsl):DesktopPet.observe_codex_presence(pet,(generation,value))
    def test_does_not_close_before_codex_was_seen(self):
        pet=self.pet()
        for _ in range(5):self.deliver(pet,set())
        pet.close.assert_not_called()
    def test_closes_after_three_confirmed_absences(self):
        pet=self.pet();self.deliver(pet,{(1,1.)})
        for _ in range(2):self.deliver(pet,set());pet.close.assert_not_called()
        self.deliver(pet,set());pet.close.assert_called_once()
    def test_unknown_read_breaks_the_absence_streak(self):
        pet=self.pet();self.deliver(pet,{(1,1.)})
        for value in (set(),set(),None,set(),set()):self.deliver(pet,value)
        pet.close.assert_not_called();self.deliver(pet,set());pet.close.assert_called_once()
    def test_remaining_window_or_quick_restart_cancels_close(self):
        pet=self.pet()
        for value in ({(1,1.),(2,2.)},{(2,2.)},set(),set(),{(3,3.)},set(),set()):self.deliver(pet,value)
        pet.close.assert_not_called()
        self.deliver(pet,set());pet.close.assert_called_once()
    def test_old_result_after_option_reset_cannot_finish_new_streak(self):
        pet=self.pet();old=pet._codex_exit_gate.generation
        pet._codex_exit_gate.reset();self.deliver(pet,{(1,1.)})
        self.deliver(pet,set());self.deliver(pet,set())
        self.deliver(pet,set(),generation=old)
        pet.close.assert_not_called();self.assertEqual(pet._codex_exit_gate.absent,2)
    def test_windows_result_arriving_after_wsl_switch_cannot_close(self):
        pet=self.pet();self.deliver(pet,{(1,1.)});self.deliver(pet,set());self.deliver(pet,set())
        self.deliver(pet,set(),wsl=True)
        pet.close.assert_not_called();self.assertFalse(pet._codex_exit_gate.seen)
    def test_wsl_poll_resets_windows_history_without_process_probe(self):
        pet=self.pet();pet._codex_exit_gate.observe({(1,1.)})
        with patch('codex_connection.is_wsl_source',return_value=True),patch('threading.Thread') as thread:
            DesktopPet.poll_codex_presence(pet)
        thread.assert_not_called();self.assertFalse(pet._codex_exit_gate.seen)
    def test_disabled_or_closing_pet_ignores_old_results(self):
        for disabled in (True,False):
            pet=self.pet();self.deliver(pet,{(1,1.)});self.deliver(pet,set());self.deliver(pet,set())
            if disabled:pet.settings['codex_exit']=False
            else:pet._codex_closing=True
            self.deliver(pet,set());pet.close.assert_not_called()
    def test_worker_tags_results_and_errors_are_unknown(self):
        pet=self.pet();generation=pet._codex_exit_gate.generation
        def thread(**kwargs):return SimpleNamespace(start=kwargs['target'])
        with patch('codex_connection.is_wsl_source',return_value=False),patch('codex_startup.desktop_sessions',side_effect=OSError('read failed')),patch('threading.Thread',side_effect=thread):
            DesktopPet.poll_codex_presence(pet)
        pet.codexPresence.emit.assert_called_once_with((generation,None))
        self.deliver(pet,None);self.assertFalse(pet._codex_polling);pet.close.assert_not_called()
    def test_real_thread_delivers_tagged_result_through_qt_queue(self):
        from PySide6.QtCore import QCoreApplication,QObject,Signal
        app=QCoreApplication.instance() or QCoreApplication([])
        class Presence(QObject):changed=Signal(object)
        emitter=Presence();pet=self.pet();pet.codexPresence=SimpleNamespace(emit=emitter.changed.emit)
        emitter.changed.connect(lambda packet:DesktopPet.observe_codex_presence(pet,packet))
        with patch('codex_connection.is_wsl_source',return_value=False),patch('codex_startup.desktop_sessions',return_value={(1,1.)}):
            DesktopPet.poll_codex_presence(pet);deadline=time.monotonic()+2
            while pet._codex_polling and time.monotonic()<deadline:app.processEvents();time.sleep(.002)
        self.assertFalse(pet._codex_polling);self.assertTrue(pet._codex_exit_gate.seen);pet.close.assert_not_called()

if __name__=='__main__':unittest.main()
