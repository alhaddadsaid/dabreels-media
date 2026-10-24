"""Finds title cards in a silent film and reads their text with OCR.

usage: python3 cards.py <film_id> <out_dir>

A title card is a stretch of at least 1.5 s where the picture barely moves
and OCR finds real words. Writes <out_dir>/<film_id>/cards/cards.json
(start, end, English text, OCR confidence) plus numbered frame grids so a
person can check the text before translating it.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402  (shares download/probe helpers and films.json)

FPS = 2
PW, PH = 160, 120


def still_segments(src, trim):
    proc = subprocess.Popen(['ffmpeg', '-nostdin', '-loglevel', 'error', '-ss', str(trim), '-i', src,
                             '-an', '-vf', f'fps={FPS},scale={PW}:{PH},format=gray',
                             '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    size = PW * PH
    prev, flags = None, []
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).astype(np.float32).reshape(PH, PW)
        motion = 99.0 if prev is None else float(np.abs(f - prev).mean())
        flags.append(motion < 4.0 and f.std() > 12)  # still, and not a blank frame
        prev = f
    proc.wait()
    segs, start = [], None
    for k, fl in enumerate(flags + [False]):
        if fl and start is None:
            start = k
        if not fl and start is not None:
            if k - start >= 3:
                segs.append((trim + start / FPS - 0.5, trim + k / FPS))
            start = None
    return segs


def ocr(src, t, path):
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{t:.2f}', '-i', src,
                    '-frames:v', '1', '-vf', 'scale=1440:-2,format=gray', path], check=True)
    r = subprocess.run(['tesseract', path, 'stdout', '--psm', '6', 'tsv'],
                       capture_output=True, text=True)
    words, confs = [], []
    for line in r.stdout.splitlines()[1:]:
        cols = line.split('\t')
        if len(cols) == 12 and cols[11].strip():
            try:
                c = float(cols[10])
            except ValueError:
                continue
            if c > 30:
                words.append(cols[11].strip())
                confs.append(c)
    text = ' '.join(words)
    real = [w for w in words if re.fullmatch(r"[A-Za-z][A-Za-z'’.,!?;:\-—\"“”]*", w) and
            len(re.sub(r'[^A-Za-z]', '', w)) >= 2]
    conf = sum(confs) / len(confs) if confs else 0
    return text, len(real), conf


def main():
    film_id, out_root = sys.argv[1], sys.argv[2]
    film = next(f for f in build.SPEC['films'] if f['id'] == film_id)
    trim = float(film.get('trim_start', 0))
    work = os.path.join('/tmp/media', film_id)
    os.makedirs(work, exist_ok=True)
    url = film['sources'][0]
    src = build.download(url, os.path.join(work, 'source' + os.path.splitext(url)[1]))
    cdir = os.path.join(out_root, film_id, 'cards')
    os.makedirs(cdir, exist_ok=True)
    cards = []
    for a, b in still_segments(src, trim):
        mid = (a + b) / 2
        img = os.path.join(work, 'ocr.png')
        text, nreal, conf = ocr(src, mid, img)
        if nreal < 2 or conf < 55:
            continue
        if cards and cards[-1]['text'] == text and a - cards[-1]['end'] < 1.5:
            cards[-1]['end'] = round(b, 2)  # same card split by a flicker
            continue
        n = len(cards) + 1
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-ss', f'{mid:.2f}', '-i', src,
                        '-frames:v', '1', '-vf', 'scale=640:-2', '-q:v', '4',
                        os.path.join(cdir, f'{n:03d}.jpg')], check=True)
        cards.append({'n': n, 'start': round(max(0.0, a), 2), 'end': round(b, 2),
                      'text': text, 'conf': round(conf), 'image': f'{n:03d}.jpg'})
        print(n, round(a, 1), text[:90], flush=True)
    json.dump(cards, open(os.path.join(cdir, 'cards.json'), 'w'), indent=1, ensure_ascii=False)
    # numbered grids (2 x 3) for checking
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    for g in range(0, len(cards), 6):
        group = cards[g:g + 6]
        inputs, tiles = [], ''
        for j in range(6):
            if j < len(group):
                c = group[j]
                inputs += ['-i', os.path.join(cdir, c['image'])]
                tiles += (f"[{j}:v]scale=640:480:force_original_aspect_ratio=decrease,"
                          f"pad=640:480:(ow-iw)/2:(oh-ih)/2,drawtext=fontfile={font}:text='{c['n']}':"
                          f"x=10:y=10:fontsize=40:fontcolor=yellow:box=1:boxcolor=black@0.7[t{j}];")
            else:
                inputs += ['-f', 'lavfi', '-i', 'color=c=black:s=640x480:d=1']
                tiles += f'[{j}:v]null[t{j}];'
        subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', *inputs, '-filter_complex',
                        tiles + ''.join(f'[t{j}]' for j in range(6)) +
                        'xstack=inputs=6:layout=0_0|640_0|0_480|640_480|0_960|640_960',
                        '-frames:v', '1', '-q:v', '4', os.path.join(cdir, f'grid_{g // 6 + 1:02d}.jpg')],
                       check=True)
    print(film_id, len(cards), 'title cards')


if __name__ == '__main__':
    main()
