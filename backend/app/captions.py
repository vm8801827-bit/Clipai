def make_ass(segments, clip_start, clip_end, path, style_name='classic'):
    def stamp(seconds):
        cs = int(max(0, seconds) * 100)
        h, cs = divmod(cs, 360000)
        m, cs = divmod(cs, 6000)
        sec, cs = divmod(cs, 100)
        return f'{h}:{m:02}:{sec:02}.{cs:02}'
    sizes = {'classic': 48, 'bold': 56, 'minimal': 42}
    margins = {'classic': 120, 'bold': 135, 'minimal': 105}
    size = sizes.get(style_name, 48)
    margin = margins.get(style_name, 120)
    header = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n'
        '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Default,DejaVu Sans,{size},&H00FFFFFF,&H0000D7FF,&H00101010,&H80000000,1,0,1,3,1,2,40,40,{margin},1\n\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    rows = []
    for seg in segments:
        words = [w for w in (seg.get('words') or []) if w['start'] < clip_end and w['end'] > clip_start]
        for offset in range(0, len(words), 8):
            group = words[offset:offset + 8]
            if not group:
                continue
            a = max(clip_start, float(group[0]['start']))
            b = min(clip_end, float(group[-1]['end']))
            if b <= a:
                continue
            tokens = []
            for word in group:
                cs = max(1, int((min(clip_end, word['end']) - max(clip_start, word['start'])) * 100))
                value = str(word['text']).replace('{', '(').replace('}', ')')
                tokens.append('{\\kf' + str(cs) + '}' + value)
            rows.append('Dialogue: 0,' + stamp(a-clip_start) + ',' + stamp(b-clip_start) + ',Default,,0,0,0,,' + ' '.join(tokens))
    path.write_text(header + '\n'.join(rows) + '\n', encoding='utf-8')
    return bool(rows)
