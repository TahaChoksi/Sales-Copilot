# Google Meet capture harness

User-started, English-first audio capture for the local Sales Copilot backend.
It captures the selected meeting tab and optionally the salesperson's microphone;
it does not capture video frames or identify individual remote participants.

See [backend/VOICE.md](../backend/VOICE.md) for installation, the exact extension
Origin configuration, controls, privacy boundaries and verification limitations.

```bash
npm ci --prefix extension
npm run build --prefix extension
npm test --prefix extension
```

Run commands from the repository root. Load `extension/` as an unpacked Chrome
extension after building. Source is under `src/`; generated `build/` and
`node_modules/` are ignored. The manifest requests only `activeTab`, `tabCapture`
and access to `http://127.0.0.1:8000/*`. There are no content scripts, cloud
endpoints, browser-storage persistence or frontend runtime dependencies.
