"""Isolate Qt modules and cap hangs; do not let one native event loop hide results."""
import concurrent.futures,hashlib,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;HERE=ROOT/'本地实装/回归验收';HERE.mkdir(parents=True,exist_ok=True)
phase=sys.argv[1] if len(sys.argv)>1 else 'current'
from build_local import source_hashes as current_sources
def run(path):
    began=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='bailong-regression-') as folder:
        env=os.environ.copy();env.update(LOCALAPPDATA=folder,APPDATA=str(Path(folder)/'roaming'),CODEX_HOME=str(Path(folder)/'codex'),QT_QPA_PLATFORM='offscreen',PYTHONIOENCODING='utf-8',BAILONG_ISOLATED='1')
        budget=120 if path.stem=='test_interaction_batch' else 75
        code="import faulthandler,unittest;faulthandler.dump_traceback_later("+str(budget-10)+");unittest.main(module="+repr(path.stem)+",verbosity=2)"
        p=subprocess.Popen([sys.executable,'-c',code],cwd=path.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            stdout,stderr=p.communicate(timeout=budget);rc=p.returncode
        except subprocess.TimeoutExpired:
            # Windows venv python.exe is a launcher: terminate its owned child
            # too, otherwise it retains the pipes and communicate never returns.
            import psutil
            try:children=psutil.Process(p.pid).children(recursive=True)
            except psutil.Error:children=[]
            for child in reversed(children):
                try:child.kill()
                except psutil.Error:pass
            if p.poll() is None:p.kill()
            stdout,stderr=p.communicate(timeout=10);rc='timeout'
        output=(stdout+stderr).decode('utf-8',errors='replace')
        result=dict(module=path.stem,returncode=rc,seconds=round(time.monotonic()-began,2),timeoutSeconds=budget)
        (HERE/f'{phase}-{path.stem}.log').write_text(output,encoding='utf-8')
        import re
        count=re.search(r'Ran (\d+) tests?',output);result['tests']=int(count[1]) if count else 0
        if rc!=0:result['tail']=output[-4500:]
        return result
paths=sorted((ROOT/'app').glob('test_*.py'))
paths += [ROOT/name for name in ('test_release_version.py','test_release_retention.py','test_local_workflow.py')]
expected_modules=sorted(p.stem for p in paths)
if len(sys.argv)>2:
    requested=set(sys.argv[2:]);unknown=requested-set(expected_modules)
    if unknown:raise SystemExit('Unknown test modules: '+', '.join(sorted(unknown)))
    paths=[p for p in paths if p.stem in requested]
if not paths:raise SystemExit('No tests selected')
initial_hashes=current_sources()
from storage_locations import install_root
guard_path=install_root()/'installations.json'
guard_before=guard_path.read_bytes() if guard_path.is_file() else None
if guard_before is not None:(HERE/f'{phase}-installation-manifest-backup.json').write_bytes(guard_before)
records=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for result in pool.map(run,paths):
        records.append(result);print(json.dumps({k:v for k,v in result.items() if k!='tail'}),flush=True)
source_hashes=current_sources()
guard_after=guard_path.read_bytes() if guard_path.is_file() else None
proof=dict(scope='full' if sorted(p.stem for p in paths)==expected_modules else 'targeted',expectedModules=expected_modules,phase=phase,sourceHashes=source_hashes,sourceUnchangedDuringTests=source_hashes==initial_hashes,installationManifestUnchanged=guard_after==guard_before,modules=len(records),tests=sum(r['tests'] for r in records),passed=bool(records) and source_hashes==initial_hashes and guard_after==guard_before and all(r['returncode']==0 and r['tests']>0 for r in records),records=records)
(HERE/f'{phase}-regressions.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(modules=proof['modules'],tests=proof['tests'],failed=[r['module'] for r in records if r['returncode']!=0])))
raise SystemExit(0 if proof['passed'] else 1)
