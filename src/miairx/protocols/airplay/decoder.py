"""SDP-configured RAOP decoding through the public PyAV API."""

import struct


class UnsupportedAudioError(ValueError):
    pass


class AudioDecoder:
    def __init__(self, sdp: str):
        attrs = {}
        for line in sdp.splitlines():
            if line.startswith("a=") and ":" in line:
                key, value = line[2:].split(":", 1)
                attrs[key] = value.strip()
        mapping = attrs.get("rtpmap", "").split()
        if len(mapping) != 2:
            raise UnsupportedAudioError("Missing SDP rtpmap")
        self.payload_type = int(mapping[0])
        encoding = mapping[1].split("/")
        self.codec_name = encoding[0].lower()
        self.sample_rate = int(encoding[1]) if len(encoding) > 1 else 44100
        self.channels = int(encoding[2]) if len(encoding) > 2 else 2
        self.frame_samples = 352
        self._context = None
        self._resampler = None
        if self.codec_name == "applelossless":
            import av

            fmt = [int(n) for n in attrs.get("fmtp", "").split()]
            if len(fmt) != 12 or fmt[0] != self.payload_type:
                raise UnsupportedAudioError("Invalid ALAC SDP fmtp")
            self.frame_samples, _, bits, _, _, _, self.channels, _, _, _, self.sample_rate = fmt[1:]
            if bits != 16:
                raise UnsupportedAudioError("Only 16-bit ALAC is supported")
            self._validate()
            # QuickTime ALAC atom: size, type, version, then ALACSpecificConfig.
            extra = struct.pack(">I4sIIBBBBBBHIII", 36, b"alac", 0, *fmt[1:])
            self._context = av.CodecContext.create("alac", "r")
            self._context.extradata = extra
            self._context.open()
            self._resampler = av.AudioResampler(
                format="s16",
                layout="mono" if self.channels == 1 else "stereo",
                rate=self.sample_rate,
            )
        elif self.codec_name != "l16":
            raise UnsupportedAudioError("Unsupported SDP codec")
        self._validate()

    def _validate(self):
        if (
            self.channels not in (1, 2)
            or not 8000 <= self.sample_rate <= 96000
            or not 1 <= self.frame_samples <= 4096
            or not 0 <= self.payload_type <= 127
        ):
            raise UnsupportedAudioError("Invalid audio parameters")

    def decode(self, data: bytes) -> bytes:
        if self.codec_name == "l16":
            if len(data) % (2 * self.channels):
                raise ValueError("Incomplete PCM frame")
            pcm = bytearray(len(data))
            pcm[0::2], pcm[1::2] = data[1::2], data[0::2]
            return bytes(pcm)
        import av

        output = []
        for frame in self._context.decode(av.Packet(data)):
            for packed in self._resampler.resample(frame):
                # PyAV planes may include alignment padding; only emit real samples.
                output.append(bytes(packed.planes[0])[: packed.samples * self.channels * 2])
        return b"".join(output)
