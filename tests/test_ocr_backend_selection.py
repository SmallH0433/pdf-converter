import sys
import unittest
from unittest.mock import patch

from app.core import ocr_service


class OcrBackendSelectionTests(unittest.TestCase):
    def test_intel_machine_prefers_directml_over_stale_cuda_files(self):
        with (
            patch.object(ocr_service, '_cuda_installed', return_value=True),
            patch.object(ocr_service, '_directml_installed', return_value=True),
            patch.object(ocr_service, 'has_nvidia_gpu', return_value=False),
        ):
            self.assertEqual(ocr_service._planned_backend(), 'directml')

    def test_backend_label_does_not_import_onnxruntime(self):
        previous = sys.modules.pop('onnxruntime', None)
        try:
            with patch.object(ocr_service, '_planned_backend', return_value='directml'):
                self.assertEqual(
                    ocr_service.backend_name(),
                    'GPU (DirectML)（首次识别时验证）',
                )
                self.assertNotIn('onnxruntime', sys.modules)
        finally:
            if previous is not None:
                sys.modules['onnxruntime'] = previous

    def test_directml_offer_does_not_depend_on_wmi_gpu_names(self):
        with (
            patch.object(ocr_service.platform, 'system', return_value='Windows'),
            patch.object(ocr_service, 'gpu_kind', return_value='none'),
            patch.object(ocr_service, 'gpu_names', return_value=[]),
            patch.object(ocr_service, 'has_nvidia_gpu', return_value=False),
            patch.object(ocr_service, '_cuda_installed', return_value=False),
            patch.object(ocr_service, '_directml_os_supported', return_value=True),
            patch.object(ocr_service, '_directml_installed', return_value=False),
        ):
            self.assertIn('directml', [kind for kind, _ in ocr_service.accel_offers()])


if __name__ == '__main__':
    unittest.main()
