"""One immutable plan for preview, timeline, retry and final render."""
from copy import deepcopy
from .schema import BY_ID

def composition(options,media):
    spec=deepcopy(BY_ID[options['template_id']])
    if options.get('color'):spec['color']=options['color']
    scenes=deepcopy(options.get('scenes') or [])
    if not scenes:
        for i,sec in enumerate(spec['shots']):
            m=media[i%len(media)]
            candidates=m.get('analysis',{}).get('candidates',[])
            candidate=candidates[(i//len(media))%len(candidates)]['start'] if candidates else 0
            start=min(candidate,max(0,m['duration']-sec))
            text=(options.get('captions') or spec['caption'])
            scenes.append({'clip_id':m['id'],'start':round(start,3),'duration':sec,'text':text[i] if i<len(text) else spec['caption'][i]})
    by_id={m['id']:m for m in media}
    for i,s in enumerate(scenes):
        if s['clip_id'] not in by_id:raise ValueError('장면의 영상은 선택한 원본에 포함되어야 합니다.')
        if s['start']>=by_id[s['clip_id']]['duration']:raise ValueError('컷 시작 시간이 원본 길이를 초과했습니다.')
        s['duration']=round(s['duration']*30)/30
        if i==0 and options.get('hook'):s['text']=options['hook']
        if i==len(scenes)-1 and options.get('cta'):s['text']=options['cta']
    spec['shots']=[s['duration'] for s in scenes];spec['caption']=[s['text'] for s in scenes];spec['duration']=sum(spec['shots'])
    if any(w['end']>spec['duration']+.001 for w in options.get('words',[])):raise ValueError('자막이 영상 종료 시간을 초과합니다.')
    return {'spec':spec,'scenes':scenes,'options':deepcopy(options)}

def checklist(options):
    text=' '.join(str(options.get(k,'')) for k in ['hook','cta','product','benefits','audience'])
    text+=' '+' '.join(s.get('text','') for s in options.get('scenes',[]))
    flagged=[word for word in ['최저가','100%','무조건','보장','완치','최고','1위'] if word in text]
    platform=options.get('platform','youtube')
    specific={
        'youtube':['YouTube Studio의 유료 프로모션 포함 설정을 확인합니다.','설명란의 제휴 링크 고지와 Shorts 음원의 상업적 이용 범위를 확인합니다.'],
        'instagram':['Instagram의 브랜디드 콘텐츠/유료 파트너십 라벨 필요 여부를 확인합니다.','브랜드 파트너 태그 승인과 비즈니스 계정에서의 음원 사용 범위를 확인합니다.'],
        'tiktok':['TikTok의 콘텐츠 공개 설정에서 내 브랜드 또는 타사 브랜드 홍보를 표시합니다.','상업용 음악 라이브러리 또는 별도 상업 이용 라이선스를 확인합니다.'],
    }
    return {'platform':platform,'flags':flagged,'items':[
        '영상·음원·인물의 광고 이용 권리를 확인했습니다.',
        '성능·가격·후기 표현을 입증할 근거를 확인했습니다.',
        '광고/협찬/제휴 고지를 확인하고 플랫폼의 유료 프로모션 표시를 설정합니다.',
        '음원 사용 범위 및 게시 시점의 플랫폼 광고 규정을 확인합니다.'
    ]+specific[platform],'notice':'자동 검사는 법적 승인이나 플랫폼 심사 통과를 보장하지 않습니다.'}
