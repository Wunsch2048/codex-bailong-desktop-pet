"""Compile the real installer error formatter; retain all isolated test files.

No downloads, installer startup, security setting changes or cleanup.
"""
import json
import subprocess
import time
from pathlib import Path

from package_program_installer import compiler_paths

root = Path(__file__).resolve().parent.parent
work = root / 'build' / ('installer-errors-' + str(time.time_ns()))
work.mkdir(parents=True)
shared = work / 'ProgramPatchBootstrap.cs'
shared.write_text((root / 'tools/ProgramPatchBootstrap.cs').read_text(encoding='utf-8')
                  .replace('@@VERSION@@', '1.0.1').replace('@@PAYLOAD_SHA@@', '0' * 64), encoding='utf-8')
harness = work / 'ErrorHarness.cs'
harness.write_text(r'''
using System;
using System.IO;
using System.ComponentModel;
static class ErrorHarness {
    static int count;
    static void Check(Exception e, string expected) {
        var text=LatestProgramInstaller.DescribeFailure(e,"正在校验安装文件");
        if(!text.Contains(expected) || !text.Contains("正在校验安装文件")) throw new Exception(text);
        if(expected.Contains("错误") && (!text.Contains("检测名称和文件路径") || !text.Contains("保护历史"))) throw new Exception(text);
        count++;
    }
    static int Main() {
        Check(new Win32Exception(225),"错误 225");
        Check(new Win32Exception(226),"错误 226");
        Check(new IOException("blocked",unchecked((int)0x800700E1)),"错误 225");
        Check(new IOException("removed",unchecked((int)0x800700E2)),"错误 226");
        Check(new Exception("outer",new IOException("blocked",unchecked((int)0x800700E1))),"错误 225");
        Check(new AggregateException(new Exception("ordinary"),new Win32Exception(226)),"错误 226");
        Check(new IOException("网络连接中断"),"网络连接中断");
        Check(new Win32Exception(5,"访问被拒绝"),"访问被拒绝");
        Check(new IOException("low word only",225),"准备失败");
        var ordinary=LatestProgramInstaller.DescribeFailure(new Exception("225 virus"),null);
        if(ordinary.Contains("安全防护") || !ordinary.Contains("准备安装")) throw new Exception(ordinary);
        Console.WriteLine(count+1);return 0;
    }
}
''', encoding='utf-8')
compiler, libraries = compiler_paths()
exe = work / 'ErrorHarness.exe'
command = [str(compiler), '/nologo', '/target:exe', '/main:ErrorHarness',
           f'/out:{exe}', *[f'/reference:{p}' for p in libraries], str(shared),
           str(root / 'tools/LatestProgramInstaller.cs'), str(harness)]
compiled = subprocess.run(command, capture_output=True)
(work / 'compile.log').write_bytes(compiled.stdout + compiled.stderr)
if compiled.returncode:
    raise RuntimeError((compiled.stdout + compiled.stderr).decode(errors='replace'))
done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
result = dict(passed=done.returncode == 0, checks=done.stdout.strip(), error=done.stderr,
              evidence=str(work), scope='Real formatter with synthetic exceptions; no installer GUI or security interception')
(work / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(done.returncode)
