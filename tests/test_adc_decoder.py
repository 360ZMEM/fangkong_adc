from protocol.adc_decoder import ActiveChannelDecoder, decode_24bit_samples, encode_test_sample


def test_decode_24bit_three_active_channels_from_full_frame():
    payload = b"".join(encode_test_sample(ch + 1, ch) for ch in range(16))
    decoded = decode_24bit_samples(payload, active_channels=[0, 1, 2], total_channels=16)
    assert decoded.voltages.shape == (1, 3)
    assert decoded.raw24[0, 0] == 1
    assert decoded.raw24[0, 1] == 2
    assert decoded.raw24[0, 2] == 3
    assert decoded.stats.channel_mismatch_count == 0


def test_decode_negative_24bit():
    payload = b"".join(encode_test_sample(-1 if ch == 0 else 0, ch) for ch in range(16))
    decoded = decode_24bit_samples(payload, active_channels=[0], total_channels=16)
    assert decoded.raw24[0, 0] == -1
    assert decoded.voltages[0, 0] < 0


def test_active_channel_decoder_reassembles_packet_boundary():
    decoder = ActiveChannelDecoder([0, 1, 2])
    packet1 = b"".join(
        [
            encode_test_sample(10, 0),
            encode_test_sample(20, 1),
            encode_test_sample(30, 2),
            encode_test_sample(40, 0),
        ]
    )
    packet2 = b"".join(
        [
            encode_test_sample(50, 1),
            encode_test_sample(60, 2),
            encode_test_sample(70, 0),
            encode_test_sample(80, 1),
            encode_test_sample(90, 2),
        ]
    )

    first = decoder.decode(packet1)
    second = decoder.decode(packet2)

    assert first.raw24.tolist() == [[10, 20, 30]]
    assert second.raw24.tolist() == [[40, 50, 60], [70, 80, 90]]
    assert first.stats.channel_mismatch_count == 0
    assert second.stats.channel_mismatch_count == 0
