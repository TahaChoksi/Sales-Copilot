import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

function makeProcessor() {
  let Processor;
  const messages = [];
  const sandbox = {
    AudioWorkletProcessor: class {port = {postMessage: (value) => messages.push(value)};},
    registerProcessor: (name, constructor) => {assert.equal(name, 'pcm-capture'); Processor = constructor;},
  };
  vm.runInNewContext(readFileSync(new URL('../build/pcm-worklet.js', import.meta.url), 'utf8'), sandbox);
  return {processor: new Processor(), messages};
}

test('outputs full 100ms PCM frames, including quiet audio', () => {
  const {processor, messages} = makeProcessor();
  for (let i = 0; i < 25; i++) processor.process([[new Float32Array(128)]]);
  assert.equal(messages.length, 2);
  for (const message of messages) {
    assert.equal(message.byteLength, 3200);
    assert.ok(new Uint8Array(message).every((sample) => sample === 0));
  }
});

test('downmixes channels and encodes clipped little-endian PCM16', () => {
  const {processor, messages} = makeProcessor();
  processor.process([[new Float32Array(1600).fill(2), new Float32Array(1600).fill(2)]]);
  assert.equal(new DataView(messages[0]).getInt16(0, true), 32767);
  processor.process([[new Float32Array(1600).fill(-2)]]);
  assert.equal(new DataView(messages[1]).getInt16(0, true), -32768);
  processor.process([[new Float32Array(1600).fill(1), new Float32Array(1600).fill(-1)]]);
  assert.equal(new DataView(messages[2]).getInt16(0, true), 0);
});

test('flush preserves a partial final frame and pads only its tail', () => {
  const {processor, messages} = makeProcessor();
  processor.process([[new Float32Array(128).fill(0.5)]]);
  assert.equal(messages.length, 0);
  processor.port.onmessage({data: {type: 'flush'}});
  assert.equal(messages.length, 2);
  const view = new DataView(messages[0]);
  assert.equal(view.getInt16(127 * 2, true), 16384);
  assert.equal(view.getInt16(128 * 2, true), 0);
  assert.equal(messages[1].type, 'flushed');
  assert.equal(processor.process([[new Float32Array(128)]]), false);
});

test('missing input preserves the source clock with zero frames', () => {
  const {processor, messages} = makeProcessor();
  for (let i = 0; i < 25; i++) processor.process([]);
  assert.equal(messages.length, 2);
});
