# Totoro Taste Model and Personalization Design

How the system learns who each user is from behavior alone, and why two people sharing the same TikTok video get different recommendations.

-----

## Part 1: What the Best Companies Learned

### Spotify: Taste Clusters from Listening Behavior

**Signals collected:** Spotify tracks explicit feedback (library saves, playlist adds, follows, skips) and implicit feedback (listening session length, track completion, repeat listens, time of day, device type). The system interprets these signals in context. A skip during a “What’s New” browsing session weighs less than a skip during a focused playlist session because the user’s intent differs.

**How they represent taste:** Spotify does not build one monolithic taste profile per user. They segment each user into multiple taste clusters using matrix factorization and playlist co-occurrence analysis. A user who listens to lo-fi beats while working and death metal while running gets two separate clusters, not a blended average. Discover Weekly draws from a mix of affinity data (what you gravitate toward) and similarity data (what people like you also enjoy) to find tracks you have not heard.

**Taste drift:** Spotify processes feedback in context-rich listening sessions. The system uses recency weighting so recent behavior matters more than old behavior. Their Daily Mix playlists update continuously as listening patterns shift. They also introduced an “Exclude from Taste Profile” feature in 2024, letting users manually remove tracks that polluted their profile (gym music, kids’ songs, viral TikTok audio).

**What failed first:** Pure collaborative filtering based on individual user-song play counts produced inaccurate recommendations because users have broad, diverse listening profiles. Two users who both play Song A and Song B are not necessarily similar. Spotify shifted collaborative filtering to focus on playlist co-occurrence instead of raw consumption data. Songs that appear together in user-created playlists produce stronger similarity signals than songs that the same user streamed independently.

**Cold start approach:** For new users, Spotify falls back to content-based filtering. Audio analysis via convolutional neural networks extracts features (tempo, energy, acousticness, danceability) from raw audio spectrograms. This lets Spotify categorize a brand new track even with zero listens. For new users, Spotify starts with popular content filtered by demographic and geographic signals, then adapts within the first few listening sessions using rapid learning from initial interactions.

**Key lesson for Totoro:** Do not build one flat user profile. Segment taste into clusters. A user who saves street food spots in Bangkok and fine dining in Paris is two different people depending on context. Weight recent signals over old ones. And do not depend on collaborative filtering alone when your user base is small.

-----

### TikTok: Implicit Signals Over Explicit Actions

**Signals collected:** TikTok tracks explicit signals (likes, shares, saves, comments, follows) and implicit signals (video completion rate, rewatch count, watch duration, scroll speed, pause/hesitation time before scrolling). The implicit signals carry more weight. TikTok’s internal scoring framework assigns roughly 10 points for rewatch/loop behavior, 8 for complete video watch, 6 for shares, 4 for comments, 2 for likes, and -1 for quick scrolling past a video.

**How they represent taste:** TikTok builds a multidimensional behavioral profile per user. The system categorizes users not by stated interests but by observed behavioral patterns, grouping users into interest clusters based on what they actually watch through, not what they explicitly like. The algorithm assigns videos to topic clusters and interest categories, then matches content to users who have engaged with similar topics. TikTok reportedly tracks patterns that mirror psychological traits like openness to new content, cross-cultural engagement, and willingness to explore new topics.

**Taste drift:** TikTok adapts within a single session. The content-based filtering layer recommends items based on intrinsic features (hashtags, sounds, captions, on-screen text). This means the system does not need weeks of historical data to adjust. If you start watching cooking videos in a session that normally features gaming content, the feed shifts within minutes. TikTok also offers a “Not interested” button and a full FYP refresh that resets the feed as if you had a new account.

**What failed first:** Relying on explicit likes as the primary signal proved unreliable. A “like” is often a social or performative gesture. Someone likes a friend’s video out of obligation. But watching a 15-second video three times in a row is a powerful indicator of genuine interest. TikTok’s breakthrough was prioritizing time-based continuous signals over binary actions. Watch time is granular, continuous, and requires zero extra effort from the user to collect.

**Cold start approach:** For brand new users, TikTok starts with popular recent videos filtered by basic demographic signals (age, location from signup). As the user scrolls through the initial batch, every micro-interaction (how long they watch each video, what they skip, what they rewatch) immediately feeds back into the model. TikTok’s recommender systems start forming preference assumptions with as few as eight short video interactions. The short-form content format is the enabler here. In one session, a user creates 20+ data points. A Netflix session produces one or two.

**Key lesson for Totoro:** The volume of implicit signals per session matters. Totoro needs to extract maximum signal from every consult interaction, not wait for users to press a “like” button. How users phrase their queries, how fast they accept or dismiss a recommendation, what they ignore completely, these are your TikTok-equivalent implicit signals. And eight interactions is enough to start differentiating users.

-----

### Netflix: Revealed Preference Beats Stated Preference

**Signals collected:** Netflix tracks viewing history (what, how long, how often), search queries, browsing behavior (scroll depth, click-through rates, hover time on thumbnails), device type, time of day, day of week, and pause/resume/skip/rewatch patterns. Netflix also personalizes which thumbnail image each user sees for the same title, selecting the version most likely to get a click based on that user’s profile.

**How they represent taste:** Netflix builds multidimensional user taste profiles that evolve with viewing behavior, capturing both explicit signals (thumbs up/down) and implicit signals (completion, rewatching). They also tag content at extreme granularity using human taggers who assign thousands of “altgenres” or microgenres per title (ensemble cast, set in space, strong female lead, dialogue pacing, soundtrack mood). The matching happens between the user’s behavioral profile and these granular content attributes.

**Taste drift:** Netflix uses time-decay weighting and contextual signals. Preferences shift based on device (phone vs TV), time of day (morning vs late night), and day of week. Their models balance quick response to recent behavior with stability against random noise. They also use bandit algorithms that inject controlled exploration to prevent the system from becoming an echo chamber.

**What failed first:** Star ratings. Netflix discovered that users rated content based on aspiration rather than actual preference. People gave documentaries five stars and sitcoms three stars but watched sitcoms ten times more. Stated preference diverged from revealed preference. When Netflix switched to binary thumbs in 2017, ratings activity increased 200% because the cognitive load dropped and the signal aligned better with actual behavior. The thumbs data matched what people actually played. Stars reflected what people wanted to be seen liking.

**Cold start approach:** Netflix optionally prompts new users to select a few titles they like during onboarding. This is optional. If skipped, the system serves diverse, popular content and then adapts rapidly based on initial viewing behavior. The stated preferences from onboarding get superseded quickly by behavioral signals once the user starts watching. Transfer learning techniques help new models benefit from knowledge gained from similar users, accelerating cold-start learning.

**Key lesson for Totoro:** Never trust what users say they want. Trust what they do. If a user tells you they want healthy restaurants but keeps accepting fried chicken recommendations, the system should weight revealed behavior over stated intent. Binary feedback (accept/dismiss) produces denser, more reliable data than asking users to rate on a scale. And aspirational bias is real: people will share aesthetic cafes they never visit.

-----

### Airbnb: Embeddings from Sessions, Two-Sided Optimization

**Signals collected:** Airbnb uses over 200 ranking factors including price, location, amenities, time spent viewing a listing, click-through patterns, wishlisting behavior, booking history, host response time, and the likelihood that a host will accept a guest based on historical behavior. They also track category click intensity and recency, time-of-day preferences, and browsing language.

**How they represent taste:** Airbnb trains listing embeddings using a Word2Vec-inspired approach on user click sessions. Listings that appear together in the same browsing session are pushed closer in embedding space. They split sessions into “booked sessions” (where a booking happened) and “exploratory sessions” (where no booking occurred), giving extra weight to the booked listing as a global context vector. This produces a learned latent representation where similar listings cluster together. For personalization, Airbnb computes the similarity between a user’s historical booking embeddings and candidate listings in real time.

**Taste drift:** Airbnb builds separate features for short-term interest (current session clicks) and long-term preference (booking history). The ranking model combines both. They also personalize by time-of-day preference, tracking which times of day a user clicks on experiences and boosting future results that match those patterns.

**What failed first:** Basic matrix factorization and simple linear models failed because Airbnb is a two-sided marketplace. The system needs to rank listings that appeal to the guest while simultaneously deprioritizing listings where the host would reject the guest. A one-dimensional scoring function cannot handle both objectives. They also found that data on individual listings is sparse (each listing gets booked at most 365 nights per year), so they compensated with session-based embeddings that generalize across similar listings.

**Cold start approach:** For new users, Airbnb relies on the search query itself (location, dates, guest count) plus popularity signals and content-based features of listings (amenities, type, price). As the user browses, their in-session clicks immediately update the personalization features. For new listings, Airbnb uses content features (photos, amenities, location attributes) to position them in the embedding space before any booking data exists.

**Key lesson for Totoro:** Session-based embeddings are powerful for learning taste from sparse data. Totoro’s per-consult sessions (which places the user viewed, which they accepted, which they dismissed) map directly to Airbnb’s click session approach. And two-sided optimization matters: recommending a place that is closed, overcrowded, or outside a user’s price tolerance is the equivalent of recommending a listing whose host would reject the booking.

-----

## Part 2: Applying These Lessons to Totoro

### Question 1: What Signals Does the System Collect Passively?

Totoro collects three categories of signals without ever asking the user to fill in a form.

**Share signals (what they save):**

- Source type: TikTok, Instagram, link, screenshot, typed name
- Time of share: weekday/weekend, morning/evening
- Place attributes extracted: cuisine, price range, venue type, neighborhood character
- Share frequency: how often they add places (daily hoarder vs occasional saver)
- Source pattern: do they share from influencer feeds, editorial reviews, friend recommendations, or personal visits?

**Consult signals (how they search):**

- Raw query text: the exact words they use reveal priorities. “Cheap dinner nearby” vs “romantic spot for anniversary” signal different constraint hierarchies
- Query frequency: how often they consult, and about what categories
- Location at time of query: are they exploring a new city or asking about their home neighborhood?
- Time context: weekend brunch queries vs Tuesday lunch queries
- Constraint patterns: do they always mention price? Never mention distance? Always specify cuisine?

**Feedback signals (how they respond):**

- Accept: user goes with the primary recommendation
- Accept alternative: user picks an alternative instead of the primary
- Dismiss: user runs a new consult with a modified query (rephrasing signals the first recommendation missed)
- Ignore: user receives a recommendation and takes no action (weakest signal, but still informative)
- Time to decision: fast acceptance signals strong fit. Long pause followed by acceptance signals marginal fit
- Rephrase patterns: what changed between the first query and the second? That delta reveals what the system got wrong

**Derived meta-signals:**

- Acceptance rate over time: trending up means the model is converging. Trending down means taste drift or model staleness
- Source trust: does the user accept recommendations sourced from their saved places more often than discovered places, or vice versa?
- Constraint rigidity: does the user accept places outside their stated price range? If yes, the price constraint is soft. If they always dismiss places above a threshold, the constraint is hard

### Question 2: How to Represent Taste: Labels vs Latent Vectors

Do not use labels like “nightlife person” or “aesthetic food person.” Labels collapse the complexity of human taste into brittle categories. They create false boundaries. A user who saves cafes 80% of the time and nightlife venues 20% of the time is not a “cafe person.” They are a person with a dominant preference and a secondary mode.

**Use a continuous weighted vector.**

Represent each user as a numeric vector across observable taste dimensions. Every dimension is a float between 0.0 and 1.0, updated by exponential moving average as new signals arrive.

```
taste_model = {
  "user_id": "usr_abc123",
  "version": 7,
  "updated_at": "2026-03-13T10:00:00Z",

  "dimensions": {
    "price_sensitivity":    0.82,   # 0 = price-insensitive, 1 = highly price-sensitive
    "distance_tolerance":   0.35,   # 0 = only nearby, 1 = will travel far
    "cuisine_adventurousness": 0.60, # 0 = sticks to known cuisines, 1 = tries everything
    "crowd_preference":     0.25,   # 0 = avoids crowds, 1 = seeks buzz/energy
    "ambiance_weight":      0.70,   # 0 = doesn't care about vibe, 1 = ambiance-driven
    "social_proof_trust":   0.85,   # 0 = ignores trending/influencer, 1 = trusts social signals
    "novelty_seeking":      0.45,   # 0 = returns to favorites, 1 = always wants new places
    "time_sensitivity":     0.60,   # 0 = flexible timing, 1 = strict about hours/wait times
  },

  "cuisine_affinities": {
    "ramen": 0.90,
    "thai": 0.75,
    "italian": 0.40,
    "coffee": 0.85
  },

  "venue_type_affinities": {
    "cafe": 0.80,
    "restaurant": 0.65,
    "bar": 0.30,
    "street_food": 0.70
  },

  "source_trust": {
    "influencer": 0.75,
    "editorial": 0.50,
    "friend_share": 0.90,
    "personal_visit": 0.95
  },

  "temporal_patterns": {
    "weekday_lunch": ["quick", "nearby", "cheap"],
    "weekend_dinner": ["ambiance", "cuisine_match", "social_proof"],
    "travel_mode": ["novelty", "local_favorites", "distance_flexible"]
  },

  "constraint_rigidity": {
    "price": "hard",       # rarely accepts above their range
    "distance": "soft",    # sometimes accepts farther places
    "cuisine": "soft",     # open to suggestions outside preference
    "crowd_level": "hard"  # consistently avoids crowded places
  }
}
```

**Why this structure works:**

- It differentiates User A (high social_proof_trust, high ambiance_weight, low crowd_preference) from User B (low social_proof_trust, high crowd_preference, high novelty_seeking) on the same dimensions without labeling either
- Every value updates incrementally from behavior. No dimension requires explicit user input
- The ranking function reads these values directly. No LLM interpretation needed at scoring time
- Adding a new dimension later (e.g., sustainability_preference) requires adding one key, not restructuring the model

**Why not embeddings?** At your scale (solo developer, small user base), interpretable dimensions beat opaque embedding vectors. You need to debug why User A got a cafe and User B got a bar. With named dimensions, you read the vector and know. With a 128-dimensional embedding, you stare at floats. Interpretability is a feature at your stage. If you scale later, you add embeddings alongside the named vector as a secondary signal.

### Question 3: How the System Evaluates New Input Against the Taste Model

When a new place input arrives (e.g., a TikTok video of a trendy cafe), the system runs a fit score calculation before the place enters the recommendation pool.

**Step 1: Extract place attributes**

The extract-place pipeline produces structured metadata: cuisine, price_range, venue_type, neighborhood, source_type (influencer, editorial, friend, personal).

**Step 2: Calculate fit score**

```python
def calculate_taste_fit(place_attrs: dict, taste: dict) -> float:
    score = 0.0
    weights = {
        "cuisine_match": 0.25,
        "price_match": 0.20,
        "venue_type_match": 0.15,
        "source_trust_match": 0.15,
        "ambiance_match": 0.10,
        "novelty_factor": 0.15,
    }

    # Cuisine match: lookup affinity for this cuisine
    cuisine = place_attrs.get("cuisine", "unknown")
    cuisine_affinity = taste["cuisine_affinities"].get(cuisine, 0.3)  # default 0.3 for unknown
    score += weights["cuisine_match"] * cuisine_affinity

    # Price match: distance between place price level and user sensitivity
    price_level = place_attrs.get("price_level", 0.5)  # 0=cheap, 1=expensive
    price_fit = 1.0 - abs(taste["dimensions"]["price_sensitivity"] - (1.0 - price_level))
    score += weights["price_match"] * price_fit

    # Venue type match
    venue_type = place_attrs.get("venue_type", "restaurant")
    venue_affinity = taste["venue_type_affinities"].get(venue_type, 0.3)
    score += weights["venue_type_match"] * venue_affinity

    # Source trust match
    source = place_attrs.get("source_type", "unknown")
    source_affinity = taste["source_trust"].get(source, 0.4)
    score += weights["source_trust_match"] * source_affinity

    # Ambiance match (if available)
    if place_attrs.get("ambiance_score"):
        ambiance_fit = taste["dimensions"]["ambiance_weight"] * place_attrs["ambiance_score"]
        score += weights["ambiance_match"] * ambiance_fit
    else:
        score += weights["ambiance_match"] * 0.5  # neutral when unknown

    # Novelty factor: new cuisine or venue type gets a boost for adventurous users
    is_novel = cuisine not in taste["cuisine_affinities"]
    novelty_boost = taste["dimensions"]["novelty_seeking"] if is_novel else (1.0 - taste["dimensions"]["novelty_seeking"])
    score += weights["novelty_factor"] * novelty_boost

    return round(score, 3)
```

**Step 3: Use fit score at ranking time**

The fit score does not block places from being saved. Every shared place gets stored. But at consult time, the ranking function uses taste_fit as one of several weighted inputs alongside distance, open status, crowd level, and time context.

**The User A vs User B scenario:**

Same TikTok cafe video arrives. User A has high social_proof_trust (0.85), high ambiance_weight (0.70), high cafe affinity (0.80). Taste fit score: ~0.78. This place ranks high in her next consult.

User B has low social_proof_trust (0.20), low cafe affinity (0.15), high crowd_preference (0.85). Taste fit score: ~0.32. This place sinks to the bottom of his ranking or gets excluded entirely.

Same input. Opposite treatment. No labels required.

### Question 4: How the System Handles Taste Evolution

Taste changes. The party person becomes the wine bar person. The system must adapt without requiring the user to tell it anything.

**Mechanism: Exponential moving average (EMA) with configurable decay.**

```python
def update_dimension(current_value: float, new_signal: float, alpha: float = 0.15) -> float:
    """
    Alpha controls how fast the model reacts to new signals.
    0.15 = moderate responsiveness. Recent signals matter but don't erase history.
    Higher alpha = faster adaptation (good for early users with few data points).
    Lower alpha = more stability (good for mature profiles).
    """
    return round(current_value * (1 - alpha) + new_signal * alpha, 4)
```

**When updates happen:**

- After every `extract-place`: update cuisine_affinities, venue_type_affinities, source_trust based on what was shared
- After every `consult` response: update dimensions based on whether the recommendation was accepted, which alternative was picked, or whether the user rephrased
- After every rejection/rephrase: identify which constraints the user tightened and adjust constraint_rigidity

**Adaptive alpha based on profile maturity:**

```python
def get_alpha(total_interactions: int) -> float:
    if total_interactions < 10:
        return 0.30   # learn fast early, little history to protect
    elif total_interactions < 50:
        return 0.15   # moderate responsiveness
    else:
        return 0.08   # stable profile, resist noise
```

**Detecting a phase shift vs noise:**

If a user’s recent 10 shares are all wine bars when their previous 50 shares were nightclubs, that is not noise. Track a rolling window (last 10 interactions) and compare its centroid against the full profile. If the divergence exceeds a threshold (e.g., average dimension delta > 0.25 across 3+ dimensions), increase alpha temporarily to accelerate the transition.

```python
def detect_taste_shift(recent_window: list[dict], full_profile: dict, threshold: float = 0.25) -> bool:
    """Compare recent signals against full profile. Return True if shift detected."""
    deltas = []
    for dim_name, dim_value in full_profile["dimensions"].items():
        recent_avg = mean([s.get(dim_name, dim_value) for s in recent_window])
        deltas.append(abs(recent_avg - dim_value))
    significant_shifts = sum(1 for d in deltas if d > threshold)
    return significant_shifts >= 3
```

When a shift is detected, set alpha to 0.30 for the next 15 interactions, then decay back to the maturity-based default.

### Question 5: Two Users with Identical Taste

If User A and User B save the same places and phrase intent the same way, should the system treat them identically?

**Short answer: yes, until they diverge. Do not manufacture differences.**

At your scale, trying to distinguish two nearly identical users is overengineering. If their observed behavior is the same, their taste models will be the same, and their recommendations should be the same. This is correct behavior, not a bug.

**Where natural divergence appears:**

- **Temporal patterns:** User A consults on weekday lunches. User B consults on weekend nights. Same saved places, different contexts. The temporal_patterns in the taste model will diverge naturally
- **Constraint rigidity:** User A always rejects places above $15. User B accepts them occasionally. The constraint_rigidity map diverges after 5-10 consults
- **Acceptance patterns:** User A accepts primary recommendations 80% of the time. User B picks alternatives 60% of the time. This signals different risk profiles. User B is a browser who wants options. User A is a decider who wants one answer
- **Query language:** “cheap dinner nearby” vs “affordable dinner close by” are functionally identical. But “something chill tonight” vs “dinner for two” reveal different unstated constraints

**Do not try to solve this in Phase 3.** Build the taste model with enough granularity (the dimensions above) that natural divergence surfaces on its own. If two users truly behave identically across all dimensions, giving them identical recommendations is the right outcome.

**What Spotify teaches here:** Spotify does not try to differentiate two users who listen to exactly the same songs. They land in the same taste cluster and get similar Discover Weekly playlists. The differentiation comes from secondary signals (time of day, device, skip patterns) that naturally diverge over time.

### Question 6: Cold Start Strategy

A brand new user has saved zero places. They open Totoro and ask: “Good dinner nearby.”

**What the system must NOT do:**

- Ask them to fill in a preferences form
- Return nothing and say “save some places first”
- Fake personalization by pretending to know their taste

**What the system returns:**

A recommendation built entirely from the query itself plus external context.

**Cold start pipeline:**

```
Query: "Good dinner nearby"
Location: (lat, lng) from device

Step 1: Parse intent
  → cuisine: null (unspecified)
  → occasion: dinner
  → price: null (unspecified)
  → radius: nearby (default 2km)

Step 2: Skip taste model (empty, no saved places)

Step 3: Discover external candidates via Google Places API
  → Filter by: open now, within radius, restaurant category
  → Sort by: Google rating * review_count_weight (bayesian average to avoid
     places with 5.0 from 3 reviews)

Step 4: Apply population priors
  → Use city/neighborhood-level popularity data from Google Places
  → Boost places with high review counts relative to the area
  → Lightly diversify: return one popular safe bet as primary,
     two alternatives from different cuisines/price ranges

Step 5: Return with honest framing
  → Primary: "Raan Jay Fai — highly rated street food restaurant, 
     800m from you. Since I'm still learning your preferences, 
     I picked based on local popularity and proximity."
  → Alternatives: one at a different price point, one different cuisine

Step 6: Capture signals from this interaction
  → Did they accept? → Initialize taste model with positive signal 
     for the accepted place's attributes
  → Did they rephrase? → "Actually, something cheaper" → Initialize 
     price_sensitivity at 0.8
  → Did they ignore? → No update, wait for next interaction
```

**How Spotify and TikTok handle day one:**

Spotify starts new users with popular content filtered by region and age bracket, then adapts within a few sessions. TikTok shows popular recent videos to new users and starts profiling after ~8 interactions. Both companies accept that the first session will not be personalized. They optimize for speed of learning, not accuracy of the first recommendation.

**Totoro’s equivalent:** The first 1-3 consults will feel generic. The system is honest about this. By consult 5-8, with a few saved places and a few accept/reject signals, the taste model has enough data to start differentiating users noticeably.

**Bootstrap acceleration (optional, no form required):**

When a user shares their first place, extract maximum signal:

- Source type (TikTok influencer → high social_proof_trust initial value)
- Cuisine (ramen → initialize ramen affinity at 0.6)
- Price level (cheap → initialize price_sensitivity at 0.7)
- Venue type (cafe → initialize cafe affinity at 0.6)

One shared place initializes 4+ taste dimensions. Three shared places produce a usable starting profile.

### Question 7: Minimum Viable Taste Model for Two-Week Implementation

Here is what to build, what to defer, and what to skip.

**Build in two weeks (MVP taste model):**

|Component            |Implementation                                                               |Stores in                       |
|---------------------|-----------------------------------------------------------------------------|--------------------------------|
|8 core dimensions    |Float values (0.0-1.0) as shown in Question 2                                |taste_model table (JSONB column)|
|Cuisine affinities   |Dict of cuisine → float, top 10 cuisines tracked                             |taste_model table               |
|Venue type affinities|Dict of venue_type → float, 5-6 types                                        |taste_model table               |
|Source trust         |Dict of source_type → float, 4 source types                                  |taste_model table               |
|EMA update function  |Single Python function, called after extract-place and after consult feedback|AI service code                 |
|Adaptive alpha       |3-tier alpha based on total_interactions count                               |AI service code                 |
|Taste fit scoring    |Weighted sum function for ranking, 6 weighted factors                        |AI service code                 |
|Cold start fallback  |Google Places popularity + proximity when taste model is empty               |AI service code                 |
|Constraint rigidity  |Dict of constraint → “hard”/“soft”, updated from rejection patterns          |taste_model table               |
|Temporal patterns    |Dict of time_context → list of dominant constraints                          |taste_model table               |

**Defer to Phase 4 or later:**

|Component                                              |Why defer                                                                                                                                      |
|-------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
|Taste shift detection                                  |Requires 50+ interactions per user to have meaningful data. Build the detection function but do not hook it into alpha adjustment until Phase 6|
|Collaborative filtering (user-to-user similarity)      |Requires multiple active users. Irrelevant for a solo-developer portfolio demo with test accounts                                              |
|Embedding-based taste representation                   |The named dimension vector is more debuggable and sufficient for differentiation. Add embeddings as a parallel signal in Phase 6 if needed     |
|Source trust granularity (specific influencer tracking)|Requires URL parsing and creator identification. Phase 5 MCP integration is a better time                                                      |

**Skip entirely:**

|Component                  |Why skip                                                                                                  |
|---------------------------|----------------------------------------------------------------------------------------------------------|
|Onboarding questionnaire   |Contradicts the core design principle. Never ask users to describe their taste                            |
|Explicit personality labels|Collapses nuance. The vector representation handles this better                                           |
|LLM-driven taste inference |The taste model should be deterministic math, not a prompt to Claude asking “what kind of person is this?”|

**Architectural decision: JSONB is a derived cache, not the source of truth.**

The taste_model JSONB column is a computed summary derived from the interaction log. The interaction log (every share, consult, and feedback event with timestamps and raw payloads) is the source of truth. If you change dimension weights, add a new dimension, or fix a bug in the EMA calculation, recompute the taste model from the log. Never migrate JSONB data directly. Document this in decisions.md when Phase 3 implementation begins.

**Architectural decision: scoring weights live in config, not code.**

The ranking formula weights (taste_fit, distance_fit, price_fit, time_context_fit, freshness) belong in config/ranking.yaml in the AI repo. The scoring function reads weights from config at startup. Phase 6 tuning against first recommendation acceptance rate becomes a config change tested through the eval pipeline, not a code change. No weight values should be hardcoded in application code.

**Data flow for the MVP:**

```
User shares a place
  → extract-place runs
  → place stored in places table
  → embedding stored in embeddings table
  → taste_model row created (if first share) or updated via EMA
  → no user action required beyond sharing

User runs a consult
  → query parsed into structured intent
  → taste_model loaded for user
  → saved places retrieved via pgvector similarity search
  → external candidates discovered via Google Places
  → all candidates scored using weights from config/ranking.yaml:
     taste_fit * w1 + distance_fit * w2 + price_fit * w3 + 
     time_context_fit * w4 + freshness * w5
  → 1 primary + 2 alternatives returned
  → user response (accept/alternative/rephrase/ignore) captured
  → taste_model updated via EMA based on response
```

**What makes this MVP good enough:**

User A shares 5 aesthetic cafes from TikTok influencers. Her taste model shows: high ambiance_weight (0.70), high social_proof_trust (0.85), high cafe affinity (0.80), high price_sensitivity (0.75). When she asks “dinner nearby,” the system ranks aesthetic, affordable, socially-validated restaurants highest.

User B shares 5 nightlife venues from personal visits. His taste model shows: high crowd_preference (0.85), low social_proof_trust (0.20), high bar affinity (0.80), low price_sensitivity (0.30). When he asks “dinner nearby,” the system ranks energetic, late-night, higher-end restaurants highest.

Same query. Different results. No labels. No forms. Built from behavior alone.

-----

## Part 3: Tradeoffs and Risks

**Risk: Aspirational sharing.** Users share places they think they should like, not places they actually visit. Netflix saw the same pattern with star ratings. Mitigation: weight acceptance signals (from consults) higher than share signals. A shared place is an intent signal. An accepted recommendation is a revealed preference signal. Over time, the consult feedback loop corrects for aspirational sharing.

**Risk: Sparse data per user.** Unlike TikTok (20+ signals per session) or Spotify (hundreds of listens per week), Totoro users might share 2-3 places per week and run 1-2 consults. Mitigation: extract maximum signal from each interaction. One share produces 4+ dimension updates. One consult response produces updates to acceptance rate, constraint rigidity, and temporal patterns. Adaptive alpha ensures the model learns fast when data is sparse.

**Risk: Cold start feels impersonal.** The first few recommendations will feel generic. Mitigation: be honest in the response framing. Say “Based on local popularity and your location” for cold-start recommendations. Transition to “Based on your saved spots and past preferences” once the taste model has 5+ data points. Users forgive generic recommendations if the system is transparent and improves noticeably.

**Risk: Taste model overfits to recent behavior.** A user shares three Italian restaurants in a row (vacation in Rome), and the system thinks they only want Italian food. Mitigation: the EMA with alpha=0.15 prevents any single burst from dominating. Constraint_rigidity tracks whether a pattern is rigid or soft. And the temporal_patterns dimension captures context: “travel_mode” behavior should not overwrite “home_city” preferences.

**Risk: The 8 dimensions are wrong.** You will not know which dimensions matter most until you have real user data. Mitigation: store the full interaction history alongside the taste model. You can always recompute the model from raw signals if you change the dimensions. The taste_model table is a cache of computed state, not the source of truth. The source of truth is the interaction log.