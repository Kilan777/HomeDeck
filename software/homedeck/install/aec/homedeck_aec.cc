// homedeck-aec: acoustic echo cancellation for the HomeDeck microphones.
//
// Reads the ICS-43434 microphones (I2S card "sndrpigooglevoi", 48 kHz stereo S32) and the speaker reference that
// /etc/asound.conf copies into the ALSA loopback card (hw:Loopback,1,0, same format, clocked from the same I2S
// card), runs WebRTC AEC3 + high-pass + noise suppression (no AGC), and writes cleaned 16 kHz mono S16_LE to stdout
// for the voice pipeline. Everything played through ALSA "default" (Spotify, the browser, Jarvis' own voice,
// ringtones, sleep sounds) is in the reference, so all of it is removed from what the wake word model hears.
//
// Runtime control (live mode):
//   config file  /var/lib/homedeck/aec_runtime.conf  key=value lines: delay_ms, mic_delay_ms, ns (0 off, 1 low,
//                2 moderate, 3 high), gain, aec (0/1), gain2, mic2_delay_ms. Re-read on SIGHUP.
//   --mic2 DEV   a second microphone (a USB mic, opened through plughw so ALSA converts its format). It runs on its
//                own clock, so it is read non-blocking into a small ring and padded/trimmed to the I2S mic's frames.
//                It gets its own echo canceller fed with the same reference; the output then becomes interleaved
//                stereo S16 (left = onboard mics, right = second mic). AEC3 estimates the second mic's echo delay by
//                itself, so the mic may be moved around; mic2_delay_ms only keeps the reference ahead of the echo.
//                If the second mic goes away (unplugged) its channel repeats the first until the caller restarts.
//   SIGUSR1      dump the next dump_s seconds (default 6) of aligned mic / reference / output to /tmp/aecdump/
//                as 16 kHz mono S16 (mic.raw ref.raw out.raw), then write /tmp/aecdump/done.
//   stats        a JSON datagram every 100 ms to 127.0.0.1:47811: levels in dBFS, AEC3 ERLE and delay, underruns.
//
// Offline mode (for tuning):  homedeck-aec --offline mic.raw ref.raw out.raw [--delay MS] [--ns N] [--noaec]
//   mic/ref: 16 kHz mono S16 files (as produced by the dump); prints the ERLE the engine reports at the end.
#include <alsa/asoundlib.h>
#include <arpa/inet.h>
#include <modules/audio_processing/include/audio_processing.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <map>
#include <memory>
#include <string>
#include <vector>

static const int kRate = 16000, kFrame = 160;                 // 10 ms at 16 kHz
static const int kInRate = 48000, kInFrame = 480;             // 10 ms at 48 kHz
static const char* kConf = "/var/lib/homedeck/aec_runtime.conf";

static std::atomic<bool> g_reload{false}, g_dump{false}, g_stop{false};

struct Params { int delay_ms = 40; int mic_delay_ms = 0; int ns = 1; double gain = 16.0; bool aec = true; int dump_s = 6; bool stereo = true;
                double gain2 = 1.0; int mic2_delay_ms = 40; };

static Params load_params(const Params& base) {
  Params p = base;
  std::ifstream f(kConf);
  std::string line;
  while (std::getline(f, line)) {
    auto eq = line.find('=');
    if (eq == std::string::npos) continue;
    std::string k = line.substr(0, eq), v = line.substr(eq + 1);
    k.erase(std::remove_if(k.begin(), k.end(), ::isspace), k.end());
    try {
      if (k == "delay_ms") p.delay_ms = std::stoi(v);
      else if (k == "mic_delay_ms") p.mic_delay_ms = std::max(0, std::min(200, std::stoi(v)));
      else if (k == "ns") p.ns = std::max(0, std::min(3, std::stoi(v)));
      else if (k == "gain") p.gain = std::stod(v);
      else if (k == "aec") p.aec = std::stoi(v) != 0;
      else if (k == "dump_s") p.dump_s = std::max(1, std::min(30, std::stoi(v)));
      else if (k == "stereo_ref") p.stereo = std::stoi(v) != 0;
      else if (k == "gain2") p.gain2 = std::stod(v);
      else if (k == "mic2_delay_ms") p.mic2_delay_ms = std::max(0, std::min(200, std::stoi(v)));
    } catch (...) {}
  }
  return p;
}

// 3:1 decimator with a windowed-sinc low-pass (cutoff 7 kHz); the same filter for mic and reference keeps them alike
struct Decim3 {
  std::vector<double> h, hist;
  Decim3() {
    const int N = 48;
    h.resize(N); hist.assign(N, 0.0);
    double fc = 7000.0 / kInRate, sum = 0;
    for (int i = 0; i < N; i++) {
      double m = i - (N - 1) / 2.0;
      double s = m == 0 ? 2 * fc : std::sin(2 * M_PI * fc * m) / (M_PI * m);
      double w = 0.54 - 0.46 * std::cos(2 * M_PI * i / (N - 1));
      h[i] = s * w; sum += h[i];
    }
    for (auto& v : h) v /= sum;
  }
  // in: kInFrame samples at 48 kHz; out: kFrame samples at 16 kHz
  void run(const double* in, double* out) {
    for (int o = 0; o < kFrame; o++) {
      for (int j = 0; j < 3; j++) { hist.erase(hist.begin()); hist.push_back(in[o * 3 + j]); }
      double acc = 0;
      for (size_t i = 0; i < h.size(); i++) acc += h[i] * hist[i];
      out[o] = acc;
    }
  }
};

static snd_pcm_t* open_capture(const char* dev, bool nonblock, snd_pcm_uframes_t period, snd_pcm_uframes_t buffer) {
  snd_pcm_t* pcm = nullptr;
  if (snd_pcm_open(&pcm, dev, SND_PCM_STREAM_CAPTURE, nonblock ? SND_PCM_NONBLOCK : 0) < 0) return nullptr;
  snd_pcm_hw_params_t* hw; snd_pcm_hw_params_alloca(&hw);
  snd_pcm_hw_params_any(pcm, hw);
  snd_pcm_hw_params_set_access(pcm, hw, SND_PCM_ACCESS_RW_INTERLEAVED);
  snd_pcm_hw_params_set_format(pcm, hw, SND_PCM_FORMAT_S32_LE);
  snd_pcm_hw_params_set_channels(pcm, hw, 2);
  unsigned rate = kInRate; snd_pcm_hw_params_set_rate_near(pcm, hw, &rate, nullptr);
  snd_pcm_hw_params_set_period_size_near(pcm, hw, &period, nullptr);
  snd_pcm_hw_params_set_buffer_size_near(pcm, hw, &buffer);
  if (snd_pcm_hw_params(pcm, hw) < 0) { snd_pcm_close(pcm); return nullptr; }
  snd_pcm_prepare(pcm);
  snd_pcm_start(pcm);
  return pcm;
}

static double dbfs16(const int16_t* x, int n) {
  double s = 0; for (int i = 0; i < n; i++) s += double(x[i]) * x[i];
  return 20 * std::log10(std::sqrt(s / n) / 32768.0 + 1e-9);
}

static webrtc::AudioProcessing* make_apm(const Params& p) {
  webrtc::AudioProcessing* apm = webrtc::AudioProcessingBuilder().Create();
  webrtc::AudioProcessing::Config c;
  c.echo_canceller.enabled = p.aec;
  c.echo_canceller.mobile_mode = false;
  c.high_pass_filter.enabled = true;
  c.noise_suppression.enabled = p.ns > 0;
  if (p.ns > 0) c.noise_suppression.level = static_cast<webrtc::AudioProcessing::Config::NoiseSuppression::Level>(p.ns - 1);
  c.gain_controller1.enabled = false;
  c.gain_controller2.enabled = false;
  apm->ApplyConfig(c);
  return apm;
}

static inline int16_t clip16(double v) { return (int16_t)std::max(-32768.0, std::min(32767.0, std::round(v))); }

// Delay a 16 kHz mono frame by `ms` through a queue (keeps the reference causal for the canceller). Returns the
// frame to use: `in` itself when no delay is wanted, otherwise `scratch`.
static const int16_t* delay_line(std::deque<int16_t>& q, int ms, const int16_t* in, int16_t* scratch) {
  if (ms <= 0) { q.clear(); return in; }
  for (int i = 0; i < kFrame; i++) q.push_back(in[i]);
  size_t want = (size_t)ms * 16 + kFrame;
  while (q.size() < want) q.push_front(0);
  for (int i = 0; i < kFrame; i++) { scratch[i] = q.front(); q.pop_front(); }
  while (q.size() > want) q.pop_front();
  return scratch;
}

static int offline(int argc, char** argv) {
  if (argc < 5) { fprintf(stderr, "usage: --offline mic.raw ref.raw out.raw [--delay MS] [--ns N] [--noaec]\n"); return 2; }
  Params p; p.delay_ms = 40; p.stereo = false;
  for (int i = 5; i < argc; i++) {
    if (!strcmp(argv[i], "--delay") && i + 1 < argc) p.delay_ms = atoi(argv[++i]);
    else if (!strcmp(argv[i], "--ns") && i + 1 < argc) p.ns = atoi(argv[++i]);
    else if (!strcmp(argv[i], "--noaec")) p.aec = false;
    else if (!strcmp(argv[i], "--stereo")) p.stereo = true;
    else if (!strcmp(argv[i], "--mono")) p.stereo = false;
  }
  FILE* fm = fopen(argv[2], "rb"); FILE* fr = fopen(argv[3], "rb"); FILE* fo = fopen(argv[4], "wb");
  if (!fm || !fr || !fo) { perror("open"); return 1; }
  std::unique_ptr<webrtc::AudioProcessing> apm(make_apm(p));
  webrtc::StreamConfig sc(kRate, 1), sr(kRate, p.stereo ? 2 : 1);
  const int rch = p.stereo ? 2 : 1;
  int16_t mic[kFrame], ref[kFrame * 2], out[kFrame], rout[kFrame * 2];
  while (fread(mic, 2, kFrame, fm) == (size_t)kFrame) {
    if (fread(ref, 2, kFrame * rch, fr) != (size_t)(kFrame * rch)) memset(ref, 0, sizeof ref);
    apm->ProcessReverseStream(ref, sr, sr, rout);
    apm->set_stream_delay_ms(p.delay_ms);
    apm->ProcessStream(mic, sc, sc, out);
    fwrite(out, 2, kFrame, fo);
  }
  auto st = apm->GetStatistics();
  printf("{\"erle\": %s, \"delay\": %s}\n",
         st.echo_return_loss_enhancement ? std::to_string(*st.echo_return_loss_enhancement).c_str() : "null",
         st.delay_ms ? std::to_string(*st.delay_ms).c_str() : "null");
  fclose(fm); fclose(fr); fclose(fo);
  return 0;
}

int main(int argc, char** argv) {
  if (argc > 1 && !strcmp(argv[1], "--offline")) return offline(argc, argv);
  const char* micdev = "hw:CARD=sndrpigooglevoi,DEV=0";
  const char* refdev = "hw:Loopback,1,0";
  const char* micdev2 = nullptr;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--mic") && i + 1 < argc) micdev = argv[++i];
    else if (!strcmp(argv[i], "--mic2") && i + 1 < argc) micdev2 = argv[++i];
    else if (!strcmp(argv[i], "--ref") && i + 1 < argc) refdev = argv[++i];
  }
  signal(SIGHUP, [](int) { g_reload = true; });
  signal(SIGUSR1, [](int) { g_dump = true; });
  signal(SIGTERM, [](int) { g_stop = true; });
  signal(SIGINT, [](int) { g_stop = true; });
  signal(SIGPIPE, [](int) { g_stop = true; });

  Params p = load_params(Params());
  snd_pcm_t* mic = open_capture(micdev, false, kInFrame, kInFrame * 10);
  if (!mic) { fprintf(stderr, "homedeck-aec: cannot open mic %s\n", micdev); return 1; }
  snd_pcm_t* ref = open_capture(refdev, true, 1024, 8192);       // loopback: period must match the card timer (1024)
  if (!ref) fprintf(stderr, "homedeck-aec: no reference %s, running without echo cancellation\n", refdev);
  const bool dual = micdev2 != nullptr;                             // output becomes stereo (onboard, second mic)
  snd_pcm_t* mic2 = nullptr;
  if (dual) {
    mic2 = open_capture(micdev2, true, kInFrame, kInFrame * 40);
    if (!mic2) fprintf(stderr, "homedeck-aec: cannot open second mic %s; its channel repeats the first\n", micdev2);
    else fprintf(stderr, "homedeck-aec: second mic %s\n", micdev2);
  }

  std::unique_ptr<webrtc::AudioProcessing> apm(make_apm(p));
  std::unique_ptr<webrtc::AudioProcessing> apm2(dual ? make_apm(p) : nullptr);
  webrtc::StreamConfig sc(kRate, 1);
  Decim3 dmic, dref, dref2, dmic2;
  // second mic: its own clock, so a ring of 48 kHz mono samples with a little slack; frames are padded when it
  // starves and a 10 ms frame is dropped when it runs ahead (a few ms per minute at typical USB clock error)
  std::vector<int32_t> m2tmp(kInFrame * 4 * 2);
  std::deque<double> m2ring; bool m2_running = false; long underruns2 = 0, drops2 = 0; int m2_fail = 0;
  std::deque<int16_t> mic2delay;
  double mono2[kInFrame], m16b[kFrame];
  int16_t mic2_16[kFrame], mic2_delayed[kFrame], out2[kFrame], both[kFrame * 2];
  double acc_mic2 = 0, acc_out2 = 0;
  FILE *dm2 = nullptr, *dout2 = nullptr;
  std::vector<int32_t> mbuf(kInFrame * 2), rtmp(1024 * 2 * 8);
  std::deque<double> rring, rring2;                                // reference at 48 kHz (left, right), waiting to be consumed
  bool ref_running = false; int ref_idle = 0; long underruns = 0;
  std::deque<int16_t> micdelay;                                    // optional mic delay line (keeps the reference causal)
  double mono[kInFrame], rmono[kInFrame], rmono2[kInFrame], m16[kFrame], r16[kFrame], r16b[kFrame];
  int16_t mic16[kFrame], ref16[kFrame], ref2[kFrame * 2], out16[kFrame], rout[kFrame * 2];
  FILE* dr2 = nullptr;

  int sock = socket(AF_INET, SOCK_DGRAM, 0);
  sockaddr_in to{}; to.sin_family = AF_INET; to.sin_port = htons(47811); to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  double acc_ref = 0, acc_mic = 0, acc_out = 0; int acc_n = 0, frame_no = 0;
  // reference band energies for the LED music visualiser (one-pole splits at ~250 Hz and ~2.5 kHz)
  double lp = 0, hp_prev_in = 0, hp = 0, e_bass = 0, e_treb = 0;
  const double a_lp = 1 - std::exp(-2 * M_PI * 250.0 / kRate), a_hp = std::exp(-2 * M_PI * 2500.0 / kRate);
  FILE *dm = nullptr, *dr = nullptr, *dout = nullptr; int dump_left = 0;

  while (!g_stop) {
    if (g_reload) {
      g_reload = false;
      Params np = load_params(p);
      bool rebuild = np.ns != p.ns || np.aec != p.aec;
      p = np;
      if (rebuild) { apm.reset(make_apm(p)); if (dual) apm2.reset(make_apm(p)); }
      fprintf(stderr, "homedeck-aec: reloaded delay=%d mic_delay=%d ns=%d gain=%.1f aec=%d gain2=%.2f mic2_delay=%d\n",
              p.delay_ms, p.mic_delay_ms, p.ns, p.gain, p.aec, p.gain2, p.mic2_delay_ms);
    }
    if (g_dump) {
      g_dump = false;
      system("mkdir -p /tmp/aecdump; rm -f /tmp/aecdump/done");
      dm = fopen("/tmp/aecdump/mic.raw", "wb"); dr = fopen("/tmp/aecdump/ref.raw", "wb"); dout = fopen("/tmp/aecdump/out.raw", "wb");
      dr2 = fopen("/tmp/aecdump/ref2.raw", "wb");
      if (dual) { dm2 = fopen("/tmp/aecdump/mic2.raw", "wb"); dout2 = fopen("/tmp/aecdump/out2.raw", "wb"); }
      dump_left = p.dump_s * 100;
    }
    // 1. ten milliseconds of microphone audio (blocking: the mic is the master clock)
    snd_pcm_sframes_t n = snd_pcm_readi(mic, mbuf.data(), kInFrame);
    if (n < 0) { snd_pcm_recover(mic, n, 1); continue; }
    if (n < kInFrame) continue;
    for (int i = 0; i < kInFrame; i++) mono[i] = 0.5 * (double(mbuf[2 * i]) + double(mbuf[2 * i + 1]));
    dmic.run(mono, m16);
    // The onboard mics are quiet, so they get a large gain (16). Applying all of it before the canceller would clip
    // loud music into a signal the linear filter cannot match, so the canceller sees a headroom-preserving part of
    // the gain and the rest is applied to its output (with clipping only there).
    const double pre = std::min(p.gain, 4.0), post = p.gain / pre;
    for (int i = 0; i < kFrame; i++) mic16[i] = clip16(m16[i] / 65536.0 * pre);

    // 1b. second microphone: drain what it has (non-blocking), then take 10 ms from the ring or pad with silence
    bool m2_have = false;
    if (mic2) {
      while (true) {
        snd_pcm_sframes_t r = snd_pcm_readi(mic2, m2tmp.data(), kInFrame * 4);
        if (r == -EAGAIN) break;
        if (r < 0) {
          if (r == -ENODEV || snd_pcm_recover(mic2, r, 1) < 0 || ++m2_fail > 50) {
            fprintf(stderr, "homedeck-aec: second mic stopped (%s); its channel repeats the first\n", snd_strerror(r));
            snd_pcm_close(mic2); mic2 = nullptr; m2ring.clear(); m2_running = false;
          } else snd_pcm_start(mic2);
          break;
        }
        m2_fail = 0;
        for (int i = 0; i < r; i++) m2ring.push_back(0.5 * (double(m2tmp[2 * i]) + double(m2tmp[2 * i + 1])));
        if (r < kInFrame * 4) break;
      }
      if (!m2_running && m2ring.size() >= (size_t)kInFrame * 3) m2_running = true;    // 30 ms of slack against USB jitter
      if (m2_running && (int)m2ring.size() >= kInFrame) {
        for (int i = 0; i < kInFrame; i++) { mono2[i] = m2ring.front(); m2ring.pop_front(); }
        m2_have = true;
        if (m2ring.size() > (size_t)kInFrame * 8) { for (int i = 0; i < kInFrame; i++) m2ring.pop_front(); drops2++; }
      } else if (m2_running) underruns2++;
    }
    if (!m2_have) for (int i = 0; i < kInFrame; i++) mono2[i] = 0;
    if (dual) { dmic2.run(mono2, m16b); for (int i = 0; i < kFrame; i++) mic2_16[i] = clip16(m16b[i] / 65536.0 * p.gain2); }

    // 2. drain whatever reference the loopback has (non-blocking), keep it in a small ring
    if (ref) {
      while (true) {
        snd_pcm_sframes_t r = snd_pcm_readi(ref, rtmp.data(), 1024);
        if (r == -EAGAIN) break;
        if (r < 0) { snd_pcm_recover(ref, r, 1); snd_pcm_start(ref); break; }
        for (int i = 0; i < r; i++) { rring.push_back(double(rtmp[2 * i])); rring2.push_back(double(rtmp[2 * i + 1])); }
        if (r < 1024) break;
      }
    }
    // start consuming only once a period and a half is buffered, so arrival jitter never starves a frame
    if (!ref_running && rring.size() >= 1536) { ref_running = true; ref_idle = 0; }
    if (ref_running) {
      if ((int)rring.size() >= kInFrame) {
        for (int i = 0; i < kInFrame; i++) { rmono[i] = rring.front(); rring.pop_front(); rmono2[i] = rring2.front(); rring2.pop_front(); }
        ref_idle = 0;
      } else {
        for (int i = 0; i < kInFrame; i++) rmono[i] = rmono2[i] = 0;
        if (++ref_idle > 10) { ref_running = false; rring.clear(); rring2.clear(); } else underruns++;
      }
      while (rring.size() > 8192) { rring.pop_front(); rring2.pop_front(); }   // never let the reference fall far behind
    } else {
      for (int i = 0; i < kInFrame; i++) rmono[i] = rmono2[i] = 0;
    }
    dref.run(rmono, r16); dref2.run(rmono2, r16b);
    for (int i = 0; i < kFrame; i++) {
      int16_t l = clip16(r16[i] / 65536.0), r = clip16(r16b[i] / 65536.0);
      ref2[2 * i] = l; ref2[2 * i + 1] = r; ref16[i] = clip16(0.5 * (double(l) + r));
    }

    // 3. optional mic delay so the reference always leads the echo
    int16_t mic_delayed[kFrame];
    const int16_t* mic_in = delay_line(micdelay, p.mic_delay_ms, mic16, mic_delayed);
    const int16_t* mic2_in = dual ? delay_line(mic2delay, p.mic2_delay_ms, mic2_16, mic2_delayed) : nullptr;

    // 4. echo cancellation
    if (p.stereo) { webrtc::StreamConfig s2(kRate, 2); apm->ProcessReverseStream(ref2, s2, s2, rout); }
    else apm->ProcessReverseStream(ref16, sc, sc, rout);
    apm->set_stream_delay_ms(p.delay_ms);
    if (apm->ProcessStream(mic_in, sc, sc, out16) != 0) memcpy(out16, mic_in, sizeof out16);
    if (post != 1.0) for (int i = 0; i < kFrame; i++) out16[i] = clip16(out16[i] * post);
    if (dual) {
      if (mic2 && apm2) {                                   // same reference, its own canceller (own echo path and delay)
        if (p.stereo) { webrtc::StreamConfig s2(kRate, 2); apm2->ProcessReverseStream(ref2, s2, s2, rout); }
        else apm2->ProcessReverseStream(ref16, sc, sc, rout);
        apm2->set_stream_delay_ms(p.delay_ms);
        if (apm2->ProcessStream(mic2_in, sc, sc, out2) != 0) memcpy(out2, mic2_in, sizeof out2);
      } else memcpy(out2, out16, sizeof out2);
      for (int i = 0; i < kFrame; i++) { both[2 * i] = out16[i]; both[2 * i + 1] = out2[i]; }
      if (fwrite(both, 2, kFrame * 2, stdout) != (size_t)kFrame * 2) break;
    } else if (fwrite(out16, 2, kFrame, stdout) != (size_t)kFrame) break;
    if (++frame_no % 2 == 0) fflush(stdout);

    if (dump_left > 0) {
      int16_t mic_full[kFrame]; for (int i = 0; i < kFrame; i++) mic_full[i] = clip16(mic_in[i] * post);
      fwrite(mic_full, 2, kFrame, dm); fwrite(ref16, 2, kFrame, dr); fwrite(out16, 2, kFrame, dout); fwrite(ref2, 2, kFrame * 2, dr2);
      if (dm2) { fwrite(mic2_in, 2, kFrame, dm2); fwrite(out2, 2, kFrame, dout2); }
      if (--dump_left == 0) {
        fclose(dm); fclose(dr); fclose(dout); fclose(dr2); dm = dr = dout = dr2 = nullptr;
        if (dm2) { fclose(dm2); fclose(dout2); dm2 = dout2 = nullptr; }
        FILE* d = fopen("/tmp/aecdump/done", "w"); if (d) fclose(d);
      }
    }

    // 5. stats every 100 ms
    auto sq = [](const int16_t* x) { double s = 0; for (int i = 0; i < kFrame; i++) s += double(x[i]) * x[i]; return s; };
    acc_ref += sq(ref16); acc_mic += sq(mic_in) * post * post; acc_out += sq(out16); acc_n += kFrame;
    if (dual) { acc_mic2 += sq(mic2_in); acc_out2 += sq(out2); }
    for (int i = 0; i < kFrame; i++) {
      double x = ref16[i];
      lp += a_lp * (x - lp); e_bass += lp * lp;
      hp = a_hp * (hp + x - hp_prev_in); hp_prev_in = x; e_treb += hp * hp;
    }
    if (frame_no % 10 == 0) {
      auto db = [&](double s) { return 20 * std::log10(std::sqrt(s / acc_n) / 32768.0 + 1e-9); };
      auto st = apm->GetStatistics();
      char msg[520];
      double rr = std::sqrt(acc_ref / acc_n), rb = std::sqrt(e_bass / acc_n), rt = std::sqrt(e_treb / acc_n);
      double rm = std::sqrt(std::max(0.0, acc_ref - e_bass - e_treb) / acc_n);
      e_bass = e_treb = 0;
      int n = snprintf(msg, sizeof msg, "{\"ref\":%.1f,\"mic\":%.1f,\"out\":%.1f,\"erle\":%s,\"delay\":%s,\"underruns\":%ld,\"ref_running\":%s,\"delay_hint\":%d,\"rr\":%.1f,\"rb\":%.1f,\"rm\":%.1f,\"rt\":%.1f",
               db(acc_ref), db(acc_mic), db(acc_out),
               st.echo_return_loss_enhancement ? std::to_string(*st.echo_return_loss_enhancement).c_str() : "null",
               st.delay_ms ? std::to_string(*st.delay_ms).c_str() : "null", underruns, ref_running ? "true" : "false", p.delay_ms, rr, rb, rm, rt);
      if (dual) {
        auto st2 = apm2 ? apm2->GetStatistics() : st;
        snprintf(msg + n, sizeof msg - n, ",\"mic2\":%.1f,\"out2\":%.1f,\"mic2_ok\":%s,\"erle2\":%s,\"delay2\":%s,\"underruns2\":%ld,\"drops2\":%ld}",
                 db(acc_mic2), db(acc_out2), mic2 ? "true" : "false",
                 st2.echo_return_loss_enhancement ? std::to_string(*st2.echo_return_loss_enhancement).c_str() : "null",
                 st2.delay_ms ? std::to_string(*st2.delay_ms).c_str() : "null", underruns2, drops2);
      } else snprintf(msg + n, sizeof msg - n, "}");
      sendto(sock, msg, strlen(msg), 0, (sockaddr*)&to, sizeof to);
      acc_ref = acc_mic = acc_out = acc_mic2 = acc_out2 = 0; acc_n = 0;
    }
  }
  if (ref) snd_pcm_close(ref);
  if (mic2) snd_pcm_close(mic2);
  snd_pcm_close(mic);
  return 0;
}
