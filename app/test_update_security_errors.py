"""Pure exception simulation; never enable AV, execute a sample or delete files."""
import unittest
from pathlib import Path
from unittest.mock import patch
from app_updates import UpdateError
from program_updates import stage_failure,cleanup_stage

class UpdateSecurityErrorTests(unittest.TestCase):
 def test_explicit_windows_security_codes_are_actionable(self):
  for code in (225,226):
   error=OSError('blocked');error.winerror=code
   text=stage_failure(error);self.assertIn(str(code),text);self.assertIn('保护历史记录',text);self.assertNotIn('允许',text)
 def test_wrapped_os_cause_preserves_security_reason(self):
  inner=OSError('blocked');inner.winerror=225
  outer=ValueError('generic');outer.__cause__=inner
  self.assertIn('225',stage_failure(outer))
 def test_only_written_executable_disappearing_is_a_possible_quarantine(self):
  error=FileNotFoundError(2,'missing',str(Path('stage')/'BailongEnhanced.exe'))
  self.assertNotIn('隔离',stage_failure(error,False));self.assertIn('可能',stage_failure(error,True))
  other=FileNotFoundError(2,'missing',str(Path('stage')/'runtime.dll'))
  self.assertNotIn('隔离',stage_failure(other,True))
 def test_permission_and_integrity_failures_are_not_mislabelled_as_antivirus(self):
  error=PermissionError('denied');error.winerror=5
  self.assertEqual(stage_failure(error),'denied');self.assertEqual(stage_failure(ValueError('校验不匹配')),'校验不匹配')
 def test_cleanup_cannot_mask_primary_failure_but_success_cannot_hide_cleanup_error(self):
  with patch('program_updates.remove_owned_tree',side_effect=PermissionError('cleanup denied')) as cleanup:
   cleanup_stage(Path('source.pending'),Path('.'),True);cleanup.assert_called_once()
   with self.assertRaises(PermissionError):cleanup_stage(Path('source.pending'),Path('.'),False)
if __name__=='__main__':unittest.main()
