"""Check exact strict exit codes and durable evidence, not merely a nonzero exit."""
from pathlib import Path
import json,subprocess,sys,tempfile


def check(executable):
    for mode,kind,expected in (('off','interpreter',0),('observe','interpreter',0),
            ('strict','interpreter',86),('strict','oracle',86),('strict','compiler',86),
            ('observe','bad-report',74),('invalid','interpreter',64)):
        with tempfile.TemporaryDirectory() as temp:
            report=Path(temp)/'audit.json'
            if kind=='bad-report':report.mkdir()
            run=subprocess.run([str(executable),mode,kind,str(report)],capture_output=True,text=True,timeout=10)
            if run.returncode!=expected:raise RuntimeError((mode,kind,run.returncode,run.stdout,run.stderr))
            if expected==74:
                assert 'cannot write report' in run.stderr
            elif mode in ('observe','strict'):
                data=json.loads(report.read_text(encoding='utf-8'))
                assert data['enabled'] and not data['no_fallback_observed'] and not data['qualification_complete']
                if mode=='strict':
                    assert 'PSX_STATIC_VIOLATION' in run.stderr
                    if kind=='compiler':assert data['compiler_requests']==1 and data['first_interpreter'] is None
                    elif kind=='oracle':assert data['oracle_instruction_attempts']==1 and data['first_interpreter']['pc']=='0xBFC01000'
                    else:assert data['dirty_instruction_attempts']==1 and data['first_interpreter']['pc']=='0xA0030000'
            else:assert not report.exists()
    print('PASS: seven static-audit cases; both interpreters/compiler stop before fallback; report failures fail closed')

if __name__=='__main__':check(Path(sys.argv[1]).resolve())
