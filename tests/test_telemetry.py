import unittest
from unittest.mock import patch, Mock

from evo_experiments import monitor


class HardwareTelemetryTests(unittest.TestCase):
    def setUp(self):
        with monitor._cpu_lock:
            monitor._previous_cpu = None

    def test_sample_without_nvidia_still_reports_system_metrics(self):
        with patch.object(monitor.shutil, "which", return_value=None):
            sample = monitor.sample_nvidia_smi()
        self.assertIn("sampled_at", sample)
        self.assertIn("ram_used_percent", sample)
        self.assertIn("cpu_logical_cores", sample)
        self.assertIn("load_average_1m", sample)
        self.assertFalse(sample["gpu_available"])
        self.assertIsNone(sample["gpu_memory_used_percent"])

    def test_cpu_utilization_uses_counter_delta(self):
        with patch.object(monitor.Path, "read_text", return_value="cpu 100 0 100 800 0 0 0 0 0 0"):
            first = monitor._cpu()
        self.assertIsNone(first["cpu_utilization_percent"])
        with patch.object(monitor.Path, "read_text", return_value="cpu 150 0 150 900 0 0 0 0 0 0"):
            second = monitor._cpu()
        self.assertEqual(second["cpu_utilization_percent"], 50.0)

    def test_gpu_query_reports_memory_percent_and_processes(self):
        gpu = Mock(stdout='"NVIDIA Test GPU", 75, 8192, 16384, 65, 220.5\n')
        processes = Mock(stdout='1234, /usr/bin/llama-server, 4096\n')
        with patch.object(monitor.shutil, "which", return_value="/usr/bin/nvidia-smi"), \
             patch.object(monitor.subprocess, "run", side_effect=[gpu, processes]):
            sample = monitor.sample_nvidia_smi()
        self.assertTrue(sample["gpu_available"])
        self.assertEqual(sample["gpu_memory_used_percent"], 50.0)
        self.assertEqual(sample["gpu_utilization_percent"], 75.0)
        self.assertEqual(sample["gpu_processes"][0]["pid"], 1234)
        self.assertEqual(sample["gpu_processes"][0]["process_name"], "/usr/bin/llama-server")
        self.assertNotIn("command", sample["gpu_processes"][0])


if __name__ == "__main__":
    unittest.main()
