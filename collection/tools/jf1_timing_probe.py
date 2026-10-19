"""Record the independently running default/no-deferral semantic A/B sessions."""
from pathlib import Path
import argparse
import json
from diagnostics import Client

def observe(port):
    client=Client(port);gpu=client.query('gpu_state')
    return dict(frame=client.query('frame')['frame'],display_disabled=gpu['disabled'],
        gpu_frame=gpu['ws']['cur_frame'],last_3d_frame=gpu['ws']['last_3d_frame'],
        registers=client.query('get_registers'),irq=client.query('irq_exc_stats'),
        cdrom=client.query('cdrom_state'),compilation=client.query('autocompile_status'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--default-port',type=int,default=4394)
    parser.add_argument('--comparison-port',type=int,default=4395);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=dict(method='Headless semantic A/B; same disc, BIOS and audited cache, PSX_OVERLAY_UNIT_DEFER differs. This is not a graphics/performance qualification.',
        default_defer=observe(args.default_port),no_defer=observe(args.comparison_port))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps({key:{field:value[field] for field in ('frame','display_disabled','gpu_frame','last_3d_frame')}
        for key,value in report.items() if isinstance(value,dict)},indent=2))
