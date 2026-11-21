import sqlite3
import tempfile
from pathlib import Path
import unittest
from evo_experiments.intelligence import assess_workload, discover_runtimes, estimate_runtime, initialize_profiles, kv_cache_estimate_mib, list_profiles, save_profile

class HardwareIntelligenceTests(unittest.TestCase):
    def test_kv_formula_includes_k_and_v_and_margin(self):
        self.assertEqual(kv_cache_estimate_mib(4096,32,8,128,2,2),round(4096*32*8*128*4/1048576*1.15,1))
    def test_invalid_kv_dimensions_rejected(self):
        with self.assertRaises(ValueError): kv_cache_estimate_mib(4096,0,8,128)
    def test_missing_architecture_stays_unknown(self):
        result=estimate_runtime({"context_size":65536},{"gpu_memory_total_mib":16384,"gpu_memory_used_mib":8000})
        self.assertIsNone(result["kv_cache_mib_estimate"]); self.assertEqual(result["fit_assessment"],"unknown")
    def test_headroom_is_reported(self):
        result=estimate_runtime({},{"gpu_memory_total_mib":16384,"gpu_memory_used_mib":4000,"ram_available_bytes":4*1024**3})
        self.assertEqual(result["vram_free_mib"],12384); self.assertEqual(result["ram_free_mib"],4096)
    def test_unknown_gpu_headroom_fails_closed(self):
        result=assess_workload({},{"kind":"benchmark","gpu_heavy":True,"estimated_vram_mib":4000})
        self.assertEqual(result["decision"],"unknown"); self.assertFalse(result["process_actions"])
    def test_reserve_prevents_oversubscription(self):
        sample={"gpu_memory_total_mib":16384,"gpu_memory_used_mib":12000,"ram_available_bytes":8*1024**3,"ram_used_percent":50}
        self.assertEqual(assess_workload(sample,{"kind":"benchmark","gpu_heavy":True,"estimated_vram_mib":4000})["decision"],"defer")
    def test_default_benchmark_is_gpu_heavy_and_unknown_fails_closed(self):
        result=assess_workload({},{"kind":"benchmark","estimated_vram_mib":2048})
        self.assertEqual(result["decision"],"unknown")
    def test_interactive_priority_does_not_preempt(self):
        result=assess_workload({},{"kind":"chat"})
        self.assertEqual(result["priority"],100); self.assertFalse(result["preemption"])
    def test_runtime_discovery_uses_process_name_and_correlates_gpu_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"4242"; root.mkdir()
            (root/"comm").write_text("llama-server")
            result=discover_runtimes([{"pid":4242,"memory_used_mib":700}],{"model":"qwen"},tmp)
            self.assertEqual(result["processes"][0]["runtime"],"llama.cpp")
            self.assertEqual(result["processes"][0]["gpu_memory_used_mib"],700)
            self.assertNotIn("argv",result["processes"][0])

    def test_profiles_persist_and_validate(self):
        db=sqlite3.connect(":memory:"); db.row_factory=sqlite3.Row; initialize_profiles(db)
        saved=save_profile(db,{"name":"Qwen baseline","model":"qwen","context_size":49152})
        self.assertEqual(list_profiles(db)[0]["id"],saved["id"])
        with self.assertRaises(ValueError): save_profile(db,{"name":"bad","context_size":-1})

if __name__=="__main__": unittest.main()
