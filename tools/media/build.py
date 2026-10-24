"""Turns one open film into vertical short-drama episodes.

usage: python3 build.py <film_id> <out_dir>

Writes to <out_dir>/<film_id>/:
  ep_01.mp4 ...   720x1280 H.264/AAC, picture centred on a blurred copy of itself
  poster.jpg      600x900 series poster (frame picked automatically)
  banner.jpg      1280x720 wide image for the home carousel
  sheet.jpg       contact sheet of candidate frames (for choosing a better poster)
  meta.json       episode cut times, durations, sources, licence and credit
  subs/           original subtitle files listed in films.json
  cards/          (silent films) title-card frames + cards.json for translation
"""
import json
import math
import os
import random
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.environ.get('MEDIA_SPEC', os.path.join(HERE, 'films.json')), encoding='utf-8'))
UA = 'DabReelsMedia/1.0 (github.com/alhaddadsaid)'
W, H = 720, 1280
MAX_ASPECT = 1.9  # wider films lose a little at the sides, so the picture stays big


def run(cmd, **kw):
    print('+', ' '.join(cmd)[:300], flush=True)
    return subprocess.run(cmd, check=True, **kw)


def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    run(['curl', '-L', '--fail', '--retry', '5', '--retry-delay', '10', '-A', UA,
         '-o', path + '.part', url])
    os.rename(path + '.part', path)
    return path


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                          'format=duration:stream=codec_type,width,height',
                          '-of', 'json', path], capture_output=True, text=True, check=True)
    j = json.loads(out.stdout)
    v = next(s for s in j['streams'] if s['codec_type'] == 'video')
    has_audio = any(s['codec_type'] == 'audio' for s in j['streams'])
    return float(j['format']['duration']), v['width'], v['height'], has_audio


def scene_times(path, threshold=0.32):
    """Timestamps of hard cuts, found on a small copy of the picture."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', path, '-an', '-sn',
                        '-vf', f"scale=160:-2,select='gt(scene,{threshold})',showinfo",
                        '-f', 'null', '-'], capture_output=True, text=True)
    times = []
    for line in r.stderr.splitlines():
        if 'showinfo' in line and 'pts_time:' in line:
            try:
                times.append(float(line.split('pts_time:')[1].split()[0]))
            except ValueError:
                pass
    return times


def plan_cuts(duration, target, scenes, window=22, min_len=45):
    """Episode boundaries close to equal lengths, snapped to scene cuts."""
    n = max(1, round(duration / target))
    cuts = [0.0]
    for k in range(1, n):
        ideal = k * duration / n
        near = [t for t in scenes if abs(t - ideal) <= window and t - cuts[-1] >= min_len]
        cuts.append(min(near, key=lambda t: abs(t - ideal)) if near else ideal)
    cuts.append(duration)
    # merge a too-short last episode
    if len(cuts) > 2 and cuts[-1] - cuts[-2] < min_len:
        cuts.pop(-2)
    return cuts


def vertical_filter(w, h):
    aspect = w / h
    crop = f"crop='min(iw,ih*{MAX_ASPECT})':ih," if aspect > MAX_ASPECT else ''
    return (f"[0:v]split[a][b];"
            f"[a]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,"
            f"boxblur=6:2,eq=brightness=-0.10:saturation=1.1,scale={W}:{H}:flags=bilinear[bg];"
            f"[b]{crop}scale={W}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]")


def encode_episode(src, start, length, w, h, out, music=None, music_offset=0.0, has_audio=True):
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
           '-ss', f'{start:.3f}', '-t', f'{length:.3f}', '-i', src]
    fade_out = max(0.0, length - 0.6)
    if music:
        cmd += ['-ss', f'{music_offset:.3f}', '-t', f'{length:.3f}', '-i', music]
        afilter = f"[1:a]afade=t=in:d=0.6,afade=t=out:st={fade_out:.3f}:d=0.6,volume=0.85[a]"
    elif has_audio:
        afilter = f"[0:a]aresample=48000,afade=t=in:d=0.25,afade=t=out:st={max(0.0, length - 0.4):.3f}:d=0.4[a]"
    else:
        afilter = None
    fc = vertical_filter(w, h) + (';' + afilter if afilter else '')
    cmd += ['-filter_complex', fc, '-map', '[v]']
    if afilter:
        cmd += ['-map', '[a]', '-c:a', 'aac', '-b:a', '128k', '-ac', '2']
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-maxrate', '2500k',
            '-bufsize', '5000k', '-g', '48', '-profile:v', 'high', '-level', '4.0',
            '-movflags', '+faststart', '-r', '24', out]
    run(cmd)


def build_music_bed(tracks, seconds, workdir, seed):
    """Joins public-domain piano recordings (with crossfades) into one long track."""
    mdir = os.path.join(workdir, 'music')
    os.makedirs(mdir, exist_ok=True)
    files = []
    for name in tracks:
        p = os.path.join(mdir, name.replace('(', '').replace(')', ''))
        try:
            base = SPEC['silent_music'].get('base', 'https://commons.wikimedia.org/wiki/Special:FilePath/')
            download(base + urllib.request.quote(name), p)
            files.append(p)
        except subprocess.CalledProcessError:
            print('music track failed:', name)
    if not files:
        raise SystemExit('no music tracks could be downloaded')
    random.Random(seed).shuffle(files)
    # normalise every track to wav first
    wavs = []
    for i, f in enumerate(files):
        wv = os.path.join(mdir, f'{i:02d}.wav')
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', f, '-ac', '2', '-ar', '48000',
             '-af', 'loudnorm=I=-18:TP=-2', wv])
        wavs.append(wv)
    order, total = [], 0.0
    while total < seconds + 60:
        for wv in wavs:
            order.append(wv)
            total += probe_audio(wv) - 3
            if total >= seconds + 60:
                break
    bed = os.path.join(mdir, 'bed.wav')
    inputs = []
    for wv in order:
        inputs += ['-i', wv]
    if len(order) == 1:
        shutil.copy(order[0], bed)
    else:
        chain, last = [], '[0:a]'
        for i in range(1, len(order)):
            lab = f'[m{i}]'
            chain.append(f'{last}[{i}:a]acrossfade=d=3:c1=tri:c2=tri{lab}')
            last = lab
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', *inputs, '-filter_complex',
             ';'.join(chain), '-map', last, '-ac', '2', '-ar', '48000', bed])
    return bed


def probe_audio(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'csv=p=0', path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def frame_score(path):
    """Rough 'interesting frame' score: contrast x colourfulness, from a tiny copy."""
    r = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', path, '-vf',
                        'scale=64:36', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                       capture_output=True, check=True)
    px = r.stdout
    n = len(px) // 3
    lum = [0.299 * px[3 * i] + 0.587 * px[3 * i + 1] + 0.114 * px[3 * i + 2] for i in range(n)]
    mean = sum(lum) / n
    if mean < 35 or mean > 215:
        return 0.0
    contrast = math.sqrt(sum((l - mean) ** 2 for l in lum) / n)
    colour = sum(abs(px[3 * i] - px[3 * i + 1]) + abs(px[3 * i + 1] - px[3 * i + 2])
                 for i in range(n)) / n
    return contrast * (10 + colour)


def make_images(src, duration, w, h, outdir, workdir, silent):
    cand_dir = os.path.join(workdir, 'cand')
    os.makedirs(cand_dir, exist_ok=True)
    times = [duration * (0.12 + 0.70 * i / 15) for i in range(16)]
    scored = []
    for i, t in enumerate(times):
        p = os.path.join(cand_dir, f'{i:02d}.png')
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{t:.2f}', '-i', src,
             '-frames:v', '1', p])
        score = frame_score(p) * (1.0 if not silent else 1.0)
        scored.append((score, t, p))
    # contact sheet with timestamps, so a person can pick a better frame later
    sheet_inputs = []
    for i, (_, t, p) in enumerate(scored):
        lab = os.path.join(cand_dir, f'l{i:02d}.jpg')
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', p, '-vf',
             f"scale=480:-2,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{t:.0f}s':x=8:y=8:fontsize=28:fontcolor=yellow:box=1:boxcolor=black@0.6",
             lab])
        sheet_inputs.append(lab)
    run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i',
         os.path.join(cand_dir, 'l%02d.jpg'), '-vf', 'scale=480:270:force_original_aspect_ratio=decrease,'
         'pad=480:270:(ow-iw)/2:(oh-ih)/2,tile=4x4', '-frames:v', '1',
         os.path.join(outdir, 'sheet.jpg')])
    best = max(scored)[2]
    best_t = max(scored)[1]
    # poster 2:3: centre crop of the frame, blurred fill if the frame is too narrow
    run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', best, '-filter_complex',
         '[0:v]split[a][b];[a]scale=600:900:force_original_aspect_ratio=increase,crop=600:900,boxblur=20:2[bg];'
         '[b]scale=-2:900,crop=min(iw\\,600):900[fg];[bg][fg]overlay=(W-w)/2:0',
         '-q:v', '3', os.path.join(outdir, 'poster.jpg')])
    run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-i', best, '-filter_complex',
         '[0:v]split[a][b];[a]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=20:2[bg];'
         '[b]scale=1280:720:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2',
         '-q:v', '3', os.path.join(outdir, 'banner.jpg')])
    return best_t


def detect_title_cards(src, outdir):
    """Finds silent-film title cards (light text on a dark, still background)."""
    import numpy as np
    fps = 2
    pw, ph = 96, 72
    proc = subprocess.Popen(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', src, '-an',
                             '-vf', f'fps={fps},scale={pw}:{ph},format=gray', '-f', 'rawvideo', '-'],
                            stdout=subprocess.PIPE)
    flags, prev, i = [], None, 0
    size = pw * ph
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).astype(np.float32).reshape(ph, pw)
        inner = f[8:-8, 8:-8]
        bright = (inner > 150).mean()
        dark = (inner < 60).mean()
        still = prev is not None and np.abs(f - prev).mean() < 3.0
        flags.append(bool(dark > 0.6 and 0.01 < bright < 0.3 and still))
        prev = f
        i += 1
    proc.wait()
    segs, start = [], None
    for k, fl in enumerate(flags + [False]):
        if fl and start is None:
            start = k
        if not fl and start is not None:
            if k - start >= 3:  # at least 1.5 s
                segs.append((start / fps - 0.5, k / fps))
            start = None
    cdir = os.path.join(outdir, 'cards')
    os.makedirs(cdir, exist_ok=True)
    cards = []
    for n, (a, b) in enumerate(segs, 1):
        mid = (a + b) / 2
        p = os.path.join(cdir, f'{n:03d}.jpg')
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{mid:.2f}', '-i', src,
             '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '4', p])
        cards.append({'n': n, 'start': round(max(0, a), 2), 'end': round(b, 2), 'image': f'{n:03d}.jpg'})
    # grids of 6 cards (2 x 3) with their numbers, for reading and translating
    for g in range(0, len(cards), 6):
        group = cards[g:g + 6]
        inputs = []
        for c in group:
            inputs += ['-i', os.path.join(cdir, c['image'])]
        tiles = ''.join(
            f"[{j}:v]scale=640:480:force_original_aspect_ratio=decrease,pad=640:480:(ow-iw)/2:(oh-ih)/2,"
            f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{c['n']}':x=10:y=10:fontsize=40:fontcolor=yellow:box=1:boxcolor=black@0.7[t{j}];"
            for j, c in enumerate(group))
        while len(group) < 6:  # pad the last grid
            j = len(group)
            inputs += ['-f', 'lavfi', '-i', 'color=c=black:s=640x480:d=1']
            tiles += f'[{j}:v]null[t{j}];'
            group = group + [None]
        layout = '0_0|640_0|0_480|640_480|0_960|640_960'
        run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', *inputs, '-filter_complex',
             tiles + ''.join(f'[t{j}]' for j in range(6)) + f'xstack=inputs=6:layout={layout}',
             '-frames:v', '1', '-q:v', '4', os.path.join(cdir, f'grid_{g // 6 + 1:02d}.jpg')])
    json.dump(cards, open(os.path.join(cdir, 'cards.json'), 'w'), indent=1)
    return len(cards)


def main():
    film_id, out_root = sys.argv[1], sys.argv[2]
    film = next(f for f in SPEC['films'] if f['id'] == film_id)
    target = film.get('episode_target_seconds', SPEC['episode_target_seconds'])
    outdir = os.path.join(out_root, film_id)
    work = os.path.join(os.environ.get('MEDIA_WORK', '/tmp/media'), film_id)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(work, exist_ok=True)

    meta = {'id': film_id, 'license': film['license'], 'credit': film['credit'],
            'sources': film.get('sources') or film.get('parts'), 'episodes': []}

    # subtitles (kept as originals; Arabic episode files are made later from cut times)
    if film.get('subtitles'):
        sdir = os.path.join(outdir, 'subs')
        os.makedirs(sdir, exist_ok=True)
        for lang, url in film['subtitles'].items():
            try:
                download(url, os.path.join(sdir, f'{lang}.srt'))
            except subprocess.CalledProcessError:
                print('subtitle failed', url)

    if film.get('parts'):
        # each short becomes one episode
        for k, url in enumerate(film['parts'], 1):
            src = download(url, os.path.join(work, f'part{k}' + os.path.splitext(url)[1]))
            dur, w, h, has_audio = probe(src)
            out = os.path.join(outdir, f'ep_{k:02d}.mp4')
            encode_episode(src, 0, dur, w, h, out, has_audio=has_audio)
            meta['episodes'].append({'n': k, 'file': f'ep_{k:02d}.mp4', 'source_part': k,
                                     'start': 0, 'end': round(dur, 2), 'duration': round(dur, 2)})
            if k == 1:
                meta['poster_time'] = make_images(src, dur, w, h, outdir, work, False)
        json.dump(meta, open(os.path.join(outdir, 'meta.json'), 'w'), indent=1, ensure_ascii=False)
        return

    url = film['sources'][0]
    src = download(url, os.path.join(work, 'source' + os.path.splitext(url.split('?')[0])[1]))
    dur, w, h, has_audio = probe(src)
    print(f'{film_id}: {dur:.1f}s {w}x{h} audio={has_audio}', flush=True)
    meta.update({'source_duration': round(dur, 2), 'source_size': [w, h]})

    music = None
    if film.get('silent'):
        music = build_music_bed(SPEC['silent_music']['tracks'], dur, work, seed=film_id)
        meta['music_credit'] = SPEC['silent_music']['credit']
        meta['title_cards'] = detect_title_cards(src, outdir)

    scenes = scene_times(src)
    cuts = plan_cuts(dur, target, scenes)
    print('cuts:', [round(c, 1) for c in cuts], flush=True)
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        out = os.path.join(outdir, f'ep_{k + 1:02d}.mp4')
        encode_episode(src, a, b - a, w, h, out, music=music, music_offset=a,
                       has_audio=has_audio and not film.get('silent'))
        meta['episodes'].append({'n': k + 1, 'file': f'ep_{k + 1:02d}.mp4', 'start': round(a, 3),
                                 'end': round(b, 3), 'duration': round(b - a, 3)})
    meta['poster_time'] = make_images(src, dur, w, h, outdir, work, bool(film.get('silent')))
    json.dump(meta, open(os.path.join(outdir, 'meta.json'), 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
