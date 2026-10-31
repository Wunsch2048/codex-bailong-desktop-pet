import unittest,tempfile,json
from pathlib import Path
from release_retention import replace_previous

class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        (self.root/'release').mkdir();(self.root/'发布说明').mkdir()
        self.policy=self.root/'发布说明/发布保留策略.json';self.old='白龙桌宠-0.6.27-一键部署.exe';self.new='白龙桌宠-0.6.28-一键部署.exe'
        self.policy.write_text(json.dumps(dict(currentReplaceableVersion='0.6.27',replaceableArtifacts=[self.old])),encoding='utf-8')
        for n in (self.old,self.new,'白龙桌宠-0.6.26-归档.exe'):(self.root/'release'/n).write_bytes(b'fixture')
        self.proof=dict(passed=True,version='0.6.28',compiledCodeVerified=True,installationVerified=True,zipVerified=True,volumesVerified=True)
    def run_replace(self):return replace_previous(self.root,'0.6.28',[self.new],self.proof)
    def test_program_artifacts_are_replaced_and_registered_with_full_package(self):
        old='bailong-desktop-pet-0.6.27-program.zip';new='bailong-desktop-pet-0.6.28-program.zip'
        for name in (old,new):(self.root/'release'/name).write_bytes(b'program')
        policy=json.loads(self.policy.read_text(encoding='utf8'));policy['replaceableProgramArtifacts']=[old];self.policy.write_text(json.dumps(policy),encoding='utf8')
        replace_previous(self.root,'0.6.28',[self.new,new],self.proof)
        self.assertFalse((self.root/'release'/old).exists());self.assertTrue((self.root/'release'/new).exists())
        self.assertEqual(json.loads(self.policy.read_text(encoding='utf8'))['replaceableProgramArtifacts'],[new])
    def test_failed_verification_or_missing_new_artifact_preserves_previous(self):
        self.proof['zipVerified']=False
        with self.assertRaises(ValueError):self.run_replace()
        self.assertTrue((self.root/'release'/self.old).exists())
        self.proof['zipVerified']=True;(self.root/'release'/self.new).unlink()
        with self.assertRaises(ValueError):self.run_replace()
        self.assertTrue((self.root/'release'/self.old).exists())
    def test_only_registered_previous_version_is_removed_and_policy_updated(self):
        result=self.run_replace();self.assertEqual(result['removed'],[self.old])
        self.assertTrue((self.root/'release/白龙桌宠-0.6.26-归档.exe').exists());self.assertTrue((self.root/'release'/self.new).exists())
        self.assertEqual(json.loads(self.policy.read_text(encoding='utf-8'))['currentReplaceableVersion'],'0.6.28')
    def test_whole_archive_release_does_not_require_unrequested_volumes(self):
        self.proof.pop('volumesVerified');self.proof['volumesRequired']=False
        self.assertTrue(self.run_replace()['passed'])
    def test_requested_volumes_still_require_verification(self):
        self.proof.pop('volumesVerified')
        with self.assertRaises(ValueError):self.run_replace()
        self.assertTrue((self.root/'release'/self.old).exists())
    def test_outside_or_wrong_version_path_rejected_before_any_deletion(self):
        for invalid in ('../outside','白龙桌宠-0.6.26-归档.exe'):
            self.policy.write_text(json.dumps(dict(currentReplaceableVersion='0.6.27',replaceableArtifacts=[self.old,invalid])),encoding='utf-8')
            with self.assertRaises(ValueError):self.run_replace()
            self.assertTrue((self.root/'release'/self.old).exists())
    def test_directory_junction_is_rejected_before_deletion(self):
        import subprocess
        outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('keep')
        linked=self.root/'release/白龙桌宠-0.6.27-目录'
        result=subprocess.run(['cmd','/c','mklink','/J',str(linked),str(outside)],capture_output=True)
        self.assertEqual(result.returncode,0)
        self.addCleanup(lambda:linked.rmdir() if linked.is_junction() else None)
        self.policy.write_text(json.dumps(dict(currentReplaceableVersion='0.6.27',replaceableArtifacts=[self.old,linked.name])),encoding='utf-8')
        with self.assertRaises(ValueError):self.run_replace()
        self.assertTrue((outside/'keep').exists());self.assertTrue((self.root/'release'/self.old).exists())

if __name__=='__main__':unittest.main()
