import numpy as np

from gui.plot_widgets import build_time_axis_ms, convert_waveform_for_display, waveform_axis_label


def test_convert_waveform_for_display_keeps_voltage_values():
    samples = np.array([[0.02], [-0.04]], dtype=np.float64)
    converted = convert_waveform_for_display(samples, "voltage", [20.0])
    assert np.allclose(converted, samples)


def test_convert_waveform_for_display_converts_to_magnetic_field():
    samples = np.array([[0.02], [-0.04]], dtype=np.float64)
    converted = convert_waveform_for_display(samples, "magnetic_field", [20.0])
    assert np.allclose(converted[:, 0], [1.0, -2.0])


def test_convert_waveform_for_display_per_channel_sensitivity():
    # 2 channels with different sensitivities
    samples = np.array([[0.02, 0.04]], dtype=np.float64)
    converted = convert_waveform_for_display(samples, "magnetic_field", [20.0, 40.0])
    # CH0: 0.02V / (20mV/μT -> 0.02V/μT) = 1.0 μT
    # CH1: 0.04V / (40mV/μT -> 0.04V/μT) = 1.0 μT
    assert np.allclose(converted[0], [1.0, 1.0])


def test_convert_waveform_for_display_requires_positive_sensitivity():
    samples = np.array([[0.02]], dtype=np.float64)
    try:
        convert_waveform_for_display(samples, "magnetic_field", [0.0])
    except ValueError as exc:
        assert "正数" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_build_time_axis_ms_uses_fixed_sample_rate():
    x = build_time_axis_ms(point_count=4, sample_rate_hz=2000)
    assert np.allclose(x, [-1.5, -1.0, -0.5, 0.0])


def test_waveform_axis_label_matches_unit_mode():
    assert waveform_axis_label("voltage") == ("Voltage", "V")
    assert waveform_axis_label("magnetic_field") == ("Magnetic Field", "μT")
