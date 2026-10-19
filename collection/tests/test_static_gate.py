from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from static_gate import assess

class StaticGateTests(unittest.TestCase):
    def fixture(self):
        return dict(game='jf1',exit_code=0,errors=[],final_input=dict(gameplay=1),
            samples=[dict(frame=100),dict(frame=400)],static_coverage_report=dict(schema=1,enabled=True,
                mode='strict',scope='process_lifetime',dirty_instruction_attempts=0,
                oracle_instruction_attempts=0,compiler_requests=0,first_interpreter=None,no_fallback_observed=True))
    def test_native_route_still_not_campaign_proof(self):
        result=assess(self.fixture());self.assertTrue(result['native_only_observed'])
        self.assertFalse(result['full_static_coverage_proven']);self.assertFalse(result['campaign_qualified'])
    def test_each_fallback_counter_and_missing_audit_rejects(self):
        for field in ('dirty_instruction_attempts','oracle_instruction_attempts','compiler_requests'):
            for value in (1,None,-1,False):
                run=self.fixture();run['static_coverage_report'][field]=value
                self.assertFalse(assess(run)['native_only_observed'])
        for audit in ({},dict(self.fixture()['static_coverage_report'],enabled=False),
                dict(self.fixture()['static_coverage_report'],scope='reset_after_boot'),
                dict(self.fixture()['static_coverage_report'],first_interpreter={'pc':'0x80010000'})):
            run=self.fixture();run['static_coverage_report']=audit
            self.assertFalse(assess(run)['native_only_observed'])
    def test_idle_failed_menu_and_short_runs_reject(self):
        for changes in (dict(exit_code=86),dict(errors=['timeout']),dict(final_input=dict(gameplay=0)),
                dict(samples=[]),dict(samples=[dict(frame=1),dict(frame=2)])):
            run=self.fixture();run.update(changes);self.assertFalse(assess(run)['native_only_observed'])

if __name__=='__main__':unittest.main()
