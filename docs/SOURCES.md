# 게임 AI 뉴스 소스 평가

2026-09-07 기준. “게임에서 쓰이는 AI”와 “AI를 활용한 게임 제작”을 모두 보되, 단순 생성형 AI 업계 뉴스는 제외한다. 활성 소스 20곳에서 뉴스 7일·명확한 제작 자료 30일 기준으로 선별한다.

## 자동 수집 중

| 소스 | 수집 | 주로 얻는 신호 | 주의점 |
|---|---|---|---|
| [GeekNews](https://news.hada.io/) | [공식 RSS](https://news.hada.io/rss/news) 후 전용 필터 | 한국어 게임 AI·코딩 도구 비교·생성 도구·추론 운영 자료 | 하루 전체 20건 중 최대 10건. 짧은 소개와 긱뉴스 링크만 게시하며 추천 수는 사용하지 않음 |
| [AI and Games](https://www.aiandgames.com/) | RSS | 전통적 게임 AI, 생성형 AI, 사례 분석, 주간 논평 | 가장 좋은 중심 소스. 유료 글은 RSS에 보이는 범위만 사용 |
| [Games and AI](https://www.gamesandai.org/) | RSS | 스튜디오의 AI 도입 단계와 조직 변화 | 글 수가 적어 보조 소스로 사용 |
| [Game Developer AI/ML/LLM](https://www.gamedeveloper.com/keyword/generative-ai) | 전체 RSS 후 필터 | 제품 발표, 개발사 사례, 법·노동·품질 논쟁 | 일반 게임 뉴스가 많아 관련성 임계값 적용 |
| [Video Games Industry Memo](https://www.videogamesindustrymemo.com/) | RSS 후 필터 | 게임 산업 관점의 AI 분석과 인터뷰 | 게임 산업 전체를 다루므로 강하게 필터링 |
| [Microsoft Game Intelligence](https://www.microsoft.com/en-us/research/group/game-intelligence/) | 공개 HTML 목록 | 월드·행동 모델, 플레이어 모델링, 인간 중심 게임 AI | 대표 페이지의 오래된 링크를 막기 위해 게시일이 있는 항목만 수집 |
| [KRAFTON AI](https://www.krafton.ai/blog/) | 페이지 내 공개 포스트 메타데이터 | PUBG Ally, CPC, 온디바이스 에이전트 등 국내 실제 구현 | 회사 공식 발표이므로 성능 주장을 독립 검증해야 함 |
| [Google DeepMind](https://deepmind.google/discover/blog/) | RSS 후 필터 | 월드 모델, 게임 환경 기반 에이전트 연구 | 대부분은 일반 AI 연구라 높은 임계값 적용 |
| [NVIDIA Developer Blog](https://developer.nvidia.com/blog/) | RSS 후 필터 | ACE, 로컬 SLM, Unreal 통합, 런타임 비용·지연 | 하드웨어/제품 홍보 관점이 강함 |
| [Inworld Blog](https://inworld.ai/blog) | RSS 후 필터 | 실시간 음성·NPC·비용·상용 운영 사례 | 공급업체 사례 연구이므로 낮은 출처 가중치 |
| [Unreal Engine](https://www.unrealengine.com/news) | 공식 Atom 피드 후 필터 | 엔진 기능, AI 플러그인·개발 워크플로 | 일반 엔진 소식이 많아 높은 임계값 적용 |
| [arXiv](https://arxiv.org/) | 공식 API 검색 | AI NPC, 게임 에이전트, 절차 생성, 플레이어 모델링 논문 | 동료평가 전 논문도 포함되므로 재현성 확인 필요 |
| [Claude Code](https://github.com/anthropics/claude-code/releases) | 공식 GitHub Releases API | 코드·리뷰·테스트·작업 자동화 기능 | 정식 릴리스의 주요 변경만. 후속 패치를 묶으며 새 기능은 별도 후보 |
| [Codex](https://github.com/openai/codex/releases) | 공식 GitHub Releases API | 코드 수정·테스트·에이전트 작업 기능 | 초안·사전 릴리스·내용 없는 수정 공지 제외 |
| [Cursor](https://cursor.com/changelog) | 공개 changelog HTML | 코딩 작업 환경·에이전트 기능 | 목록의 원래 공개일 사용, 채용·행사·회사 홍보 제외 |
| [ComfyUI](https://blog.comfy.org/feed) | 공식 RSS | 이미지·3D·텍스처·워크플로 | 챌린지·컨설팅·판매 홍보 제외. GitHub 태그를 정식 릴리스로 세지 않음 |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI/releases) | 공식 GitHub Releases API | 모델 지원·이미지 수정·반복 제작 기능 | 기능 발표·중요 제작 환경 수정만, 단순 패치 묶음 |
| [Meshy](https://www.meshy.ai/blog) | 공개 목록 + 제한된 상세 메타데이터 | 형상·메시·리깅·엔진 연동 | 상대시간을 최초 공개일로 오인하지 않고 상세 datePublished 확인 |
| [Convai](https://convai.com/blog) | 공개 목록 + 제한된 상세 메타데이터 | Unity·Unreal NPC 행동·기억·게임 상태 연동 | 명확한 개발 기능·튜토리얼만, 산업용 영업·교육 홍보 제외 |
| [80 Level AI](https://80.lv/articles/ai) | AI 전용 공개 HTML 목록 | 제작자 인터뷰·게임 적용·에셋 작업 사례 | Sponsored Article 제외. 업체 인터뷰의 수치는 독립 측정으로 표현하지 않음 |

긱뉴스는 [이용약관](https://news.hada.io/terms)과 [robots 정책](https://news.hada.io/robots.txt)을 존중하여 공식 RSS를 낮은 빈도로 수집한다. 로그인·댓글·비공개 API는 사용하지 않는다. 상세 페이지가 403을 반환하면 우회하지 않고 RSS로만 게시한다. 확인된 원문 URL만 중복 비교용 별칭으로 저장하며, 원문 주소를 얻지 못한 경우 한·영 중복 탐지에 한계가 있다.

## 좋은 자료지만 자동 수집하지 않는 곳

| 소스 | 이유와 사용법 |
|---|---|
| [GDC News & Insights](https://gdconf.com/news-insights/) | 업계 설문과 세션은 중요하지만 AI 전용 피드가 아니다. 주요 보도는 Game Developer에서 잡고 연례 보고서는 수동 검토 |
| [Ubisoft La Forge](https://www.ubisoft.com/en-us/studio/laforge) | 게임 제작에 적용되는 연구의 질은 높다. 현재 뉴스 목록이 클라이언트 렌더링이라 가벼운 수집기로 안정적인 기사 링크를 얻지 못해 비활성화 |
| [Unity Blog](https://unity.com/blog) | Unity AI·Sentis·ML-Agents 소식은 중요하다. 공식 피드 응답이 이번 검증 환경에서 안정적이지 않아 우선 제외하고 Game Developer 보도로 보완 |
| [Game AI Pro](https://www.gameaipro.com/) | 뉴스가 아니라 전통적인 게임 AI 구현을 위한 무료 참고서. 새로운 기사 알림보다 필요할 때 찾아보는 자료 |
| [AI and Games 2nd Edition](https://gameaibook.org/) | 게임 AI 전반을 체계적으로 이해하는 교재. 변화 감지 대상이 아니라 배경지식 자료 |
| [AIIDE](https://sites.google.com/view/aiide2026/)·[IEEE CoG](https://ieee-cog.org/) | 학술대회 일정과 논문 묶음은 가치가 있지만, 일일 알림에는 잡음이 커서 arXiv 검색으로 흡수 |

## 의도적으로 제외

- AI 게임 토큰, NFT, Web3 프로젝트 발표
- 출처가 없는 도구 모음 및 제휴 링크 위주의 “Top AI tools” 글
- 기사 전문 복제 사이트
- 텔레그램 재전송 채널처럼 최초 출처를 알기 어려운 피드
- 검색 결과만 대량 생성하는 AI 작성 사이트

## 선별 시 보는 질문

1. 실제 출시·오픈소스·논문·플레이 가능한 데모가 있는가?
2. NPC의 말뿐 아니라 행동, 게임 상태, 메모리와 연결되는가?
3. 지연시간, 추론 비용, GPU 점유, 실패 처리 수치가 있는가?
4. 디자이너가 결과를 통제하고 반복 수정할 수 있는가?
5. 데이터 출처, 저작권, 표시 의무, 플레이어 반응을 다루는가?
6. “가능하다”가 아니라 실제 제작·운영 단계에서 검증됐는가?
