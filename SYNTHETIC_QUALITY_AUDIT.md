# Synthetic Claims Quality Audit

Sample size: 100 randomly-selected `syn_claim_*` claims out of 202,500 total in that batch.

## Quality

- Verdict distribution in sample: {'MISLEADING': 32, 'TRUE': 19, 'UNVERIFIED': 15, 'FALSE': 34}
- Invalid/non-canonical verdicts found: none
- Average LLM-judge quality score (1-5): **3.22**
- Claims scored <=2/5: 23/100
- Near-duplicate pairs (>=0.85 text similarity) in sample: 136

**Low-quality examples:**
- (1/5) "Trending claim asserts Industry watchdog group revealed News Article enforces hidden shadowban restrictions on specific trending hashtags. (Ref ID #003237)" — incoherent, broken grammar, unclear claim
- (1/5) "Industry watchdog group ka bada daawa: Josh ne naye privacy policy ke tehat users ke call logs aur location access mandatory kar diya hai. (Ref ID #128535)" — incoherent, garbled, broken grammar, unclear claim
- (1/5) "Viral thread alleges Leaked audit memo discovered severe security loophole in TikTok exposing private profile logs. (Ref ID #143776)" — incoherent, broken grammar, unclear claim
- (1/5) "Viral thread alleges Journalism investigation discovered severe security loophole in Online exposing private profile logs. (Ref ID #151039)" — incoherent, broken grammar, unclear claim
- (2/5) "Popular claim states Whistleblower report proved Twitter/X's new AI recommendation engine prioritizes engagement over content accuracy. (Ref ID #112682)" — incoherent, broken grammar
- (1/5) "Social media post alleges Leaked audit memo documented over 100,000 automated bot accounts inflating engagement on Online. (Ref ID #150457)" — Leaks template artifacts, unclear
- (1/5) "Social media post alleges Viral tech influencer documented over 100,000 automated bot accounts inflating engagement on Threads. (Ref ID #051287)" — Leaks template artifacts, unclear
- (1/5) "Viral thread alleges Independent analysis team discovered severe security loophole in Online exposing private profile logs. (Ref ID #147437)" — Leaks template artifacts, unclear

## Diversity

- Unique categories (full population): 44
- Unique topics (full population): 45
- Over-represented categories (>30%): none
- Canonical app categories missing entirely: ['Economy', 'Health', 'Other', 'Politics', 'Science']
- Category distribution: {'History': 4.4, 'Sports': 2.2, 'Technology': 2.2, 'Pop Culture': 2.2, 'YouTube': 2.2, 'TikTok': 2.2, 'Instagram': 2.2, 'X (formerly Twitter)': 2.2, 'Pinterest': 2.2, 'LinkedIn': 2.2, 'Reddit': 2.2, 'Threads (Meta Text App)': 2.2, 'WhatsApp': 2.2, 'Snapchat': 2.2, 'Twitch': 2.2, 'Discord': 2.2, 'Vine': 2.2, 'Mastodon': 2.2, 'OnlyFans': 2.2, 'Clubhouse': 2.2, 'Bluesky': 2.2, 'BeReal': 2.2, 'Tumblr': 2.2, 'Goodreads': 2.2, 'Indian Social Media Apps': 2.2, 'Indian Internet Regulations': 2.2, 'Viral Phenomena': 2.2, 'Moj': 2.2, 'Josh': 2.2, 'Misinformation': 2.2, 'Influencer Marketing': 2.2, 'Mental Health': 2.2, 'Platforms': 2.2, 'Algorithms': 2.2, 'Artificial Intelligence': 2.2, 'E-Commerce': 2.2, 'Gaming': 2.2, 'Crypto, NFTs': 2.2, 'Podcasting': 2.2, 'Lemon8': 2.2, 'Telegram Channels': 2.2, 'Kick': 2.2, 'Farcaster': 2.2, 'Substack': 2.2}

## RAG impact (full index vs original-only)

- Verdict changed by including synthetic/added data: 0/5 test claims

### "COVID-19 vaccines cause infertility in women"
- Full index: **FALSE** (92%)
- Original-only: **FALSE** (92%)
- Synthetic/added claims in top-5: 0

### "Intermittent fasting completely eliminates the need for exercise to lose weight"
- Full index: **FALSE** (90%)
- Original-only: **FALSE** (90%)
- Synthetic/added claims in top-5: 0

### "The government uses chemtrails to control the population"
- Full index: **FALSE** (92%)
- Original-only: **FALSE** (92%)
- Synthetic/added claims in top-5: 0

### "Drinking celery juice cures autoimmune diseases"
- Full index: **FALSE** (90%)
- Original-only: **FALSE** (90%)
- Synthetic/added claims in top-5: 0

### "5G towers were installed specifically to spread COVID-19"
- Full index: **FALSE** (92%)
- Original-only: **FALSE** (92%)
- Synthetic/added claims in top-5: 0
