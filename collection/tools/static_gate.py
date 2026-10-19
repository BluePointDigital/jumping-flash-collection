"""Judge one recorded route; zero observed fallback is never campaign proof."""
from pathlib import Path
import argparse,json


def assess(run):
    reasons=[];audit=run.get('static_coverage_report') or {}
    if run.get('exit_code')!=0 or run.get('errors'):reasons.append('Runtime/harness did not finish cleanly')
    if not run.get('final_input',{}).get('gameplay'):reasons.append('No live gameplay reached')
    samples=run.get('samples',[])
    if len(samples)<2 or samples[-1].get('frame',0)-samples[0].get('frame',0)<100:
        reasons.append('Insufficient guest execution observed')
    if (audit.get('schema')!=1 or audit.get('enabled') is not True or
        audit.get('mode') not in ('observe','strict') or audit.get('scope')!='process_lifetime'):
        reasons.append('Enabled whole-process static audit missing')
    for field in ('dirty_instruction_attempts','oracle_instruction_attempts','compiler_requests'):
        count=audit.get(field)
        if type(count) is not int or count!=0:reasons.append(f'{field} is nonzero or unavailable')
    if audit.get('first_interpreter') is not None:reasons.append('First interpreter instruction recorded')
    if audit.get('no_fallback_observed') is not True:reasons.append('Observer reports fallback or is disabled')
    return dict(schema=1,game=run.get('game'),executable_sha256=run.get('executable_sha256'),
        native_only_observed=not reasons,reasons=reasons,first_interpreter=audit.get('first_interpreter'),
        mode=audit.get('mode'),full_static_coverage_proven=False,campaign_qualified=False,
        physical_deck_qualified=False,limitation='One observed route; review its scene and expand campaign coverage')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('receipt',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=assess(json.loads(args.receipt.read_text(encoding='utf-8')))
    text=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8')
    print(text,end='');raise SystemExit(0 if result['native_only_observed'] else 1)
