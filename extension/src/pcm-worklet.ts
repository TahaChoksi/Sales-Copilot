// Each source has its own 16 kHz audio context and uninterrupted sample clock.
declare abstract class AudioWorkletProcessor {
  readonly port: {
    postMessage(data: unknown, transfer?: Transferable[]): void;
    onmessage: ((event: {data: {type: string}}) => void) | null;
  };
}
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void;

class PcmCapture extends AudioWorkletProcessor {
  private frame = new Int16Array(1600);
  private offset = 0;
  private stopped = false;
  constructor() {
    super();
    this.port.onmessage = (event) => {
      if (event.data.type !== "flush") return;
      this.stopped = true;
      if (this.offset) {
        this.frame.fill(0, this.offset);
        this.emit();
      }
      this.port.postMessage({type: "flushed"});
    };
  }
  private emit(): void {
    const bytes = new ArrayBuffer(3200);
    const view = new DataView(bytes);
    for (let j = 0; j < this.frame.length; j++) view.setInt16(j * 2, this.frame[j], true);
    this.port.postMessage(bytes, [bytes]);
    this.offset = 0;
  }
  process(inputs: Float32Array[][]): boolean {
    if (this.stopped) return false;
    const channels = inputs[0];
    const length = channels?.[0]?.length ?? 128;
    for (let i = 0; i < length; i++) {
      let sample = 0;
      if (channels?.length) {
        for (const channel of channels) sample += channel[i] ?? 0;
        sample /= channels.length;
      }
      const clamped = Math.max(-1, Math.min(1, sample));
      this.frame[this.offset++] = Math.round(clamped * (clamped < 0 ? 32768 : 32767));
      if (this.offset === this.frame.length) {
        // Wire format is explicitly little-endian, independent of host endianness.
        this.emit();
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", PcmCapture);
