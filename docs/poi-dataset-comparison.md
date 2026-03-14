# Place Data Discovery: Dataset Comparison for Totoro

Research date: March 2026

## Executive Summary

For Totoro's candidate discovery pool, **Foursquare OS Places** is the recommended primary dataset. It has 106M+ POIs under Apache 2.0 (the most permissive license available), strong category coverage across all physical place types, monthly updates, and a clean Parquet format that loads directly into PostgreSQL. Overture Maps is the strongest secondary/supplementary option at 72M+ POIs under CDLA Permissive 2.0, with growing data quality from Meta and Microsoft contributions.

OpenStreetMap is powerful but carries the ODbL share-alike license, which creates legal complexity when storing data in a proprietary database and generating embeddings from it.

---

## Dataset Profiles

### 1. Foursquare Open Source Places (FSQ OS Places)

**Total POIs:** 106.2M (as of December 2025 release)

**Source:** Foursquare's proprietary Places Engine, curated by automated systems and human "Placemakers" (formerly Superusers). 15+ years of crowdsourced and verified data from Swarm check-ins, API usage, and web crawling.

**Format:** Parquet files on Amazon S3 and Hugging Face. Total download size ~10.6 GB across 25 Parquet files.

**License:** Apache 2.0. Full commercial use, storage, modification, and embedding permitted. You must preserve attribution (include their NOTICE.txt). No share-alike requirement.

**Update frequency:** Monthly releases with delta files tracking additions, updates, removals, and merges.

**Schema (OS tier, 22+ attributes):**

- fsq_place_id (unique ID)
- name, address, locality, region, postcode, country
- latitude, longitude, geom (WKB), bbox
- tel, website, email
- facebook_id, instagram, twitter
- fsq_category_ids, fsq_category_labels (1000+ categories, 6-level hierarchy)
- date_created, date_refreshed, date_closed
- placemaker_url, unresolved_flags

**Category coverage (10 parent categories):**

- Arts and Entertainment
- Business and Professional Services
- Community and Government
- Dining and Drinking
- Event
- Health and Medicine
- Landmarks and Outdoors
- Retail
- Sports and Recreation
- Travel and Transportation (includes Lodging: hotels, hostels, vacation rentals)

**What is strong:**

- Broadest coverage: restaurants, cafes, bars, hotels, hostels, attractions, museums, parks, shopping, nightlife all present
- Deep food and drink taxonomy (Foursquare's origin is restaurant/venue check-ins)
- 200+ countries covered
- Category hierarchy supports filtering at multiple granularity levels
- Delta files allow incremental sync without re-downloading the full dataset
- Social media handles (Facebook, Instagram, Twitter) included — useful for link-based place extraction in Totoro
- Apache 2.0 is the cleanest license for storing, embedding, and building a commercial product

**What is weak:**

- Data quality varies by region — Foursquare has stronger coverage in the US, Europe, and major Asian cities. Rural Southeast Asia coverage is thinner.
- No opening hours, price range, or popularity metrics in the OS tier (those are in the paid Pro/Premium tiers)
- Some user-created junk entries remain in the dataset (trolling, transient venues, personal locations). The `unresolved_flags` field helps identify suspect entries.
- No photos or ratings in the OS tier

**Southeast Asia coverage:** Foursquare historically has decent POI density in Bangkok, Singapore, Kuala Lumpur, Jakarta, and other major SE Asian cities due to Swarm usage in the region. Coverage thins significantly outside urban centers.

---

### 2. Overture Maps Foundation (Places Theme)

**Total POIs:** 72.4M (as of January 2026 release)

**Source:** Aggregated from Meta (Facebook Places), Microsoft, Foursquare (6M+ POIs added September 2025), PinMeTo, Krick, RenderSEO, DAC, and AllThePlaces. Data undergoes conflation and deduplication.

**Format:** GeoParquet files on AWS S3 and Azure Blob Storage. Total download size ~7.2 GB across 8 files. Also queryable directly via DuckDB without downloading.

**License:** CDLA Permissive 2.0 for most Places data (Meta, Microsoft sourced). Foursquare-sourced POIs carry Apache 2.0 (filter by source property). Full commercial use, storage, modification, and embedding permitted. Only requirement: make the license text available when sharing the data itself. "Results" (maps, recommendations, embeddings, analysis) have zero license obligations.

**Update frequency:** Monthly releases.

**Schema (37 attributes, many nested):**

- id (GERS — Global Entity Reference System, stable across releases)
- names (primary, common, rules — supports multilingual)
- categories (primary, alternate, basic_category, taxonomy with hierarchy)
- confidence (0-1 float)
- addresses (freeform, locality, postcode, region, country)
- websites, socials, emails, phones
- brand (names, wikidata)
- sources (dataset, record_id, confidence per source)
- operating_status (open, permanently_closed, temporarily_closed)
- geometry (WKB point)

**Category coverage:**
Uses a new taxonomy system (introduced December 2025) with hierarchical paths. Categories include: food_and_drink, accommodation, arts_and_entertainment, shopping, nightlife, active_life, health_and_medical, education, automotive, beauty_and_spa, financial_service, public_service, religious_organization, and more.

**What is strong:**

- GERS stable IDs allow syncing across releases without re-matching
- Confidence score per POI helps filter low-quality entries
- Multilingual name support built into the schema
- Operating status field (distinguishes open vs closed)
- Sources property lets you trace data provenance and filter by origin
- Clean, modern GeoParquet schema designed for analytics
- Backed by Meta and Microsoft engineering — fast-improving data quality
- DuckDB can query the data directly from S3 without full download
- New taxonomy hierarchy is well-designed for place categorization

**What is weak:**

- Smaller total count (72M vs Foursquare's 106M)
- Meta-sourced POIs (the majority) come from Facebook Pages, which skew toward businesses that have Facebook presence. Informal venues, street food stalls, and small local shops are underrepresented.
- Independent quality analysis found that POIs with confidence below 0.85 have significant location accuracy issues (50%+ are 100m+ from actual position)
- No opening hours, price range, or ratings
- No photos
- Data quality in developing regions is inconsistent — confidence scores help but require filtering

**Southeast Asia coverage:** Meta has strong presence in SE Asia (Facebook is dominant in Thailand, Philippines, Vietnam, Indonesia), so business POIs that have Facebook Pages are well-represented. Street-level informal businesses are underrepresented. Coverage is urban-heavy.

---

### 3. OpenStreetMap (POI Data)

**Total POIs:** Estimated 50-80M amenity/tourism/shop/leisure tagged nodes globally (the full planet file is 100GB+ compressed, 2TB uncompressed, but this includes roads, buildings, and all other features — POIs are a subset).

**Source:** Community-contributed. 10M+ registered users, with a core of active contributors varying by region. Contributions are volunteer-driven and verified through community review.

**Format:** PBF (Protocol Buffer Format) files. Available as full planet download or per-country/region extracts via Geofabrik (updated daily). Also accessible via Overpass API for targeted queries.

**License:** Open Database License (ODbL) 1.0. This is a share-alike (copyleft) license.

- You CAN use OSM data commercially
- You CAN store it in your database
- If you create a "derivative database" (merge OSM data with other data and the result depends on both), you MUST make that derivative database available under ODbL
- "Produced works" (maps, recommendations, app output) are NOT subject to share-alike
- Embeddings generated from OSM data are a gray area — if the embeddings constitute a derivative database (they encode information from OSM in a transformed form), they may trigger the share-alike requirement

**Update frequency:** Continuous (minutely diffs available). Geofabrik country extracts update daily.

**Schema:** Freeform key-value tags. No fixed schema. Common POI-relevant tags include:

- name, name:en, name:th (multilingual)
- amenity (restaurant, cafe, bar, hospital, pharmacy, etc.)
- tourism (hotel, hostel, guest_house, attraction, museum, viewpoint)
- shop (supermarket, clothes, convenience, etc.)
- leisure (park, garden, sports_centre, etc.)
- addr:\* (housenumber, street, city, postcode)
- opening_hours, phone, website, cuisine
- wheelchair, internet_access

**Category coverage:** Tag-based, not hierarchical. The amenity, tourism, shop, and leisure keys cover most physical place types, but categorization is inconsistent. One restaurant might be tagged `amenity=restaurant` + `cuisine=thai`, another might only have `amenity=fast_food`. Hotels are under `tourism=hotel`, parks under `leisure=park`. There is no single unified taxonomy.

**What is strong:**

- Richest attribute data of any open dataset: opening hours, cuisine types, wheelchair access, internet availability, detailed address components
- Strongest coverage for infrastructure-type POIs: bus stops, ATMs, pharmacies, post offices, government buildings
- Daily updates — fresher than any other option
- OSM has active contributor communities in Thailand and Southeast Asia (the Thai OSM community is notably active)
- Completely free, no API rate limits for bulk data downloads
- Long track record — most mature open geodata project

**What is weak:**

- ODbL share-alike creates legal complexity for storing and embedding data alongside proprietary datasets
- Coverage is extremely uneven: excellent in Europe and Japan, good in major SE Asian cities, sparse in rural areas of developing countries
- No fixed schema means extensive preprocessing to normalize data into a consistent table structure
- No confidence scores or quality metrics — you do not know which entries are stale or inaccurate
- Restaurant and nightlife coverage varies wildly by city — a tourist area in Bangkok might be well-mapped, while a local neighborhood is empty
- Hotels and accommodation are significantly underrepresented compared to commercial datasets
- Processing the planet PBF file requires specialized tools (osm2pgsql, Osmium, pyrosm)

**Southeast Asia coverage:** Thailand's OSM community is active and takes pride in data quality. Bangkok, Chiang Mai, and tourist islands have decent coverage. Vietnam, Indonesia, and Philippines have growing communities but more gaps. Rural areas across all SE Asian countries are sparse.

---

### 4. Other Notable Datasets

**AllThePlaces** — CC0 (public domain). Web scraper that extracts store locations from company websites. Covers chain businesses globally. Good for verifying chain restaurant/hotel locations. Small total count but high accuracy for what it covers. Available as GeoJSON. Already included in Overture Maps as a source.

**Yelp Open Dataset** — Academic/non-commercial use only. 6.9M reviews across 150K businesses in 11 metro areas (US and Canada only). Useful for evaluation and testing (you already plan to use it), not for production candidate discovery.

**Google Places API** — Pay-per-request ($17-$32 per 1000 requests depending on endpoint). Broadest and deepest commercial dataset but no bulk download option. Best for real-time validation and enrichment, not for building a local database. Already in your architecture for live validation during extract-place and consult flows.

**TomTom Places** — Commercial, paid. High quality but not open. TomTom contributes to Overture Maps, so some of their data flows into that dataset.

**HERE Places** — Commercial, paid. Similar situation to TomTom.

---

## Comparison Table

| Criteria                           | Foursquare OS Places                | Overture Maps                                      | OpenStreetMap                                                       |
| ---------------------------------- | ----------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| **Total POIs**                     | 106.2M                              | 72.4M                                              | ~50-80M (estimated POI subset)                                      |
| **License**                        | Apache 2.0                          | CDLA Permissive 2.0 (+ Apache 2.0 for FSQ-sourced) | ODbL 1.0 (share-alike)                                              |
| **Commercial storage + embedding** | Yes, no restrictions                | Yes, no restrictions on "Results"                  | Yes, but derivative database must be shared under ODbL              |
| **Licensing risk for Totoro**      | None                                | None                                               | Medium — embedding generation from OSM data may trigger share-alike |
| **Update frequency**               | Monthly + delta files               | Monthly                                            | Daily                                                               |
| **Download format**                | Parquet (S3, Hugging Face)          | GeoParquet (S3, Azure)                             | PBF (Geofabrik)                                                     |
| **Download size (full)**           | ~10.6 GB                            | ~7.2 GB                                            | 100 GB+ (planet), 304 MB (Thailand only)                            |
| **Schema type**                    | Fixed columns (22+)                 | Fixed columns (37, nested)                         | Freeform key-value tags                                             |
| **Category system**                | 1000+ categories, 6-level hierarchy | New taxonomy with hierarchy (Dec 2025)             | Freeform tags (amenity, tourism, shop, leisure)                     |
| **Confidence/quality score**       | No (but unresolved_flags available) | Yes (0-1 per POI)                                  | No                                                                  |
| **Stable IDs across releases**     | Yes (fsq_place_id)                  | Yes (GERS)                                         | Yes (OSM node ID)                                                   |
| **Multilingual names**             | No (single name field)              | Yes (primary, common, rules)                       | Yes (name:en, name:th, etc.)                                        |
| **Opening hours**                  | No (paid tier only)                 | No                                                 | Yes (when contributed)                                              |
| **Price range**                    | No (paid tier only)                 | No                                                 | Sometimes (varies)                                                  |
| **Contact info**                   | Phone, email, website, socials      | Phones, emails, websites, socials                  | Phone, website (when contributed)                                   |
| **Photos**                         | No (paid tier)                      | No                                                 | No                                                                  |
| **Operating status**               | date_closed field                   | open/closed/temporarily_closed                     | Sometimes tagged                                                    |

### Category Coverage by Place Type

| Place Type                      | Foursquare OS             | Overture Maps     | OpenStreetMap                               |
| ------------------------------- | ------------------------- | ----------------- | ------------------------------------------- |
| **Restaurants & Cafes**         | Excellent (origin domain) | Good (Meta Pages) | Good in tourist areas, patchy elsewhere     |
| **Bars & Nightlife**            | Excellent                 | Good              | Moderate                                    |
| **Hotels & Hostels**            | Good                      | Moderate          | Weak (significantly underrepresented)       |
| **Attractions & Museums**       | Good                      | Good              | Good (strong for cultural/historical sites) |
| **Parks & Outdoors**            | Good                      | Moderate          | Excellent (core OSM strength)               |
| **Shopping**                    | Good                      | Good (Meta Pages) | Moderate                                    |
| **Services (ATMs, pharmacies)** | Good                      | Moderate          | Excellent                                   |

### Geographic Coverage: Southeast Asia

| Region                           | Foursquare OS | Overture Maps              | OpenStreetMap             |
| -------------------------------- | ------------- | -------------------------- | ------------------------- |
| **Bangkok**                      | Strong        | Strong (Facebook dominant) | Strong (active community) |
| **Chiang Mai**                   | Moderate      | Moderate                   | Good                      |
| **Thai Islands (Samui, Phuket)** | Moderate      | Moderate                   | Moderate-Good             |
| **Singapore**                    | Strong        | Strong                     | Strong                    |
| **Kuala Lumpur**                 | Strong        | Strong                     | Good                      |
| **Jakarta / Bali**               | Good          | Strong (Facebook dominant) | Moderate                  |
| **Ho Chi Minh / Hanoi**          | Moderate      | Strong (Facebook dominant) | Moderate                  |
| **Rural SE Asia**                | Weak          | Weak                       | Weak-Moderate             |

---

## Recommended Strategy for Totoro

### Primary Dataset: Foursquare OS Places

Use FSQ OS Places as your main candidate discovery pool. Load it filtered by target cities into PostgreSQL.

**Why:**

1. Apache 2.0 license — zero risk for storing, embedding, and building commercial features
2. Largest POI count (106M) with broadest category coverage across all physical place types
3. Clean fixed schema maps directly to PostgreSQL columns
4. Monthly delta files support incremental updates without full reload
5. Social media handles (facebook_id, instagram) directly support Totoro's place extraction from TikTok/Instagram links
6. 6-level category hierarchy supports both broad filtering and fine-grained cuisine/venue type matching
7. Already in your architecture plans (referenced in your roadmap as a testing dataset)

### Secondary/Enrichment: Overture Maps Places

Use Overture Maps to fill coverage gaps, especially in SE Asian cities where Meta/Facebook Page data captures venues that Foursquare misses.

**Why:**

1. CDLA Permissive 2.0 — same zero-risk licensing for Results
2. Confidence scores let you filter to high-quality entries only (recommend >= 0.75)
3. Meta-sourced data captures Facebook-present businesses that Foursquare may miss in SE Asia
4. GERS stable IDs make ongoing sync easy
5. Multilingual names useful for Thai/local language place matching

### Live Enrichment: Google Places API

Keep Google Places API for real-time validation during extract-place and consult flows, as already designed in your architecture. Do NOT use it for bulk data loading (cost prohibitive and TOS violation).

### Avoid as Primary: OpenStreetMap

Do not use OSM as a primary candidate pool. The ODbL share-alike license creates ongoing legal complexity when you store OSM data in the same PostgreSQL database as proprietary user data and generate embeddings from it. If you merge OSM-derived fields with Foursquare data to create enriched place records, the combined dataset may be a "derivative database" under ODbL, requiring you to share it publicly.

**Exception:** OSM is safe and useful for:

- Opening hours data (query via Overpass API at read time, do not store)
- Validating addresses and coordinates
- Infrastructure POIs (ATMs, transit stops) if you keep them in a separate collection without merging into your main places table

---

## Loading Foursquare OS Places into PostgreSQL

### Step 1: Download filtered data using DuckDB

You do not need to download the full 10.6 GB dataset. Use DuckDB to query the Parquet files directly from S3 or Hugging Face and export only the cities you need.

```sql
-- Install and load required extensions
INSTALL httpfs;
LOAD httpfs;
INSTALL spatial;
LOAD spatial;

-- Example: Export Bangkok POIs (roughly within city bounds)
COPY (
  SELECT
    fsq_place_id,
    name,
    latitude,
    longitude,
    address,
    locality,
    region,
    postcode,
    country,
    tel,
    website,
    email,
    facebook_id,
    instagram,
    fsq_category_ids,
    fsq_category_labels,
    date_created,
    date_refreshed,
    date_closed
  FROM read_parquet('s3://fsq-os-places-us-east-1/release/dt=2026-02-12/places/parquet/*.parquet')
  WHERE country = 'TH'
    AND latitude BETWEEN 13.5 AND 14.0
    AND longitude BETWEEN 100.3 AND 100.9
    AND date_closed IS NULL
) TO 'bangkok_places.csv' (HEADER, DELIMITER ',');
```

### Step 2: Create the PostgreSQL table

```sql
CREATE TABLE fsq_places (
  fsq_place_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  address TEXT,
  locality TEXT,
  region TEXT,
  postcode TEXT,
  country CHAR(2),
  tel TEXT,
  website TEXT,
  email TEXT,
  facebook_id TEXT,
  instagram TEXT,
  fsq_category_ids TEXT[],
  fsq_category_labels TEXT[],
  date_created DATE,
  date_refreshed DATE,
  date_closed DATE,
  embedding vector(1536),  -- OpenAI text-embedding-3-small. Later: migrate to vector(1024) + full re-embed when swapping to Voyage 3.5-lite.
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Spatial index for distance queries
CREATE INDEX idx_fsq_places_location
  ON fsq_places USING gist (
    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
  );

-- Category index for filtering
CREATE INDEX idx_fsq_places_categories
  ON fsq_places USING gin (fsq_category_ids);

-- Vector index for semantic search (add after embeddings are generated)
CREATE INDEX idx_fsq_places_embedding
  ON fsq_places USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

### Step 3: Load the CSV

```bash
psql -d totoro -c "\COPY fsq_places(fsq_place_id, name, latitude, longitude, address, locality, region, postcode, country, tel, website, email, facebook_id, instagram, fsq_category_ids, fsq_category_labels, date_created, date_refreshed, date_closed) FROM 'bangkok_places.csv' WITH (FORMAT csv, HEADER true)"
```

### Step 4: Generate embeddings

In totoro-ai, write a batch script that:

1. Reads unembedded places from fsq_places (WHERE embedding IS NULL)
2. Constructs a text representation: `"{name} — {category_labels} — {locality}, {country}"`
3. Generates embeddings via your configured embedding model (Voyage 3.5-lite or OpenAI)
4. Writes embeddings back to the embedding column

Process in batches of 100-500 to stay within rate limits and your $20/month budget.

### Step 5: Incremental updates

Each monthly FSQ OS Places release includes delta files listing added, updated, removed, and merged place IDs. Build a Python script that:

1. Downloads the delta Parquet from S3
2. Filters to your target cities
3. Inserts new places, updates changed fields, soft-deletes removed places
4. Generates embeddings for new/updated entries only

---

## Concrete Next Steps

1. **Add a decision to decisions.md:** "ADR-XX: FSQ OS Places as primary candidate discovery pool, Overture Maps as secondary, Google Places API for live validation only. OSM excluded from primary pool due to ODbL share-alike risk."

2. **Install DuckDB locally** (`pip install duckdb` or standalone binary) and run the Bangkok export query above to validate data quality and volume before writing any loading code.

3. **Create a ClickUp task** for loading FSQ OS Places into PostgreSQL, filtered by your first target city (Bangkok).

4. **Defer Overture Maps integration** — start with one dataset, prove it works, then layer in coverage gaps later.

5. **Update api-contract.md** to note that the `source` field in consult responses can be `"saved"`, `"discovered_fsq"`, or `"discovered_google"` to distinguish candidate origins.

---

## Place Provider Abstraction

The discovery step in the consult pipeline needs a single interface to search places regardless of whether the data comes from the local FSQ table or Google Places API. Same pattern as the LLM provider abstraction (config-driven model assignments), applied to place data sources.

### Interface

A Python Protocol that both providers implement:

```python
class PlaceProvider(Protocol):
    async def search_nearby(
        self,
        lat: float,
        lng: float,
        radius_m: int,
        category: str | None,
        limit: int
    ) -> list[PlaceCandidate]: ...

    async def get_by_id(
        self,
        place_id: str
    ) -> PlaceCandidate | None: ...
```

### Implementations

**FsqLocalProvider** — queries the PostgreSQL fsq_places table using PostGIS for distance and pgvector for semantic similarity. Free, fast, no rate limits. Returns name, category, location, contact info. Missing: hours, ratings, price.

**GooglePlacesProvider** — calls Google Places API. Expensive, rate limited. Returns everything including hours, ratings, photos, price level.

### Orchestration Flow (PlaceDiscoveryService)

```
search_nearby(query, location, category)
  │
  ├── 1. Query FsqLocalProvider (PostGIS + category filter)
  │      Returns 10-20 candidates
  │
  ├── 2. If fewer than 3 results → fall back to GooglePlacesProvider
  │      (covers gaps in FSQ coverage)
  │
  ├── 3. Merge and deduplicate by name + coordinates
  │      (same place from both sources → keep FSQ, tag source)
  │
  ├── 4. After ranking narrows to top 3 final candidates:
  │      Call GooglePlacesProvider.get_by_id() for live enrichment
  │      (hours, ratings, price — only on winners, not all candidates)
  │
  └── 5. Return enriched candidates with source tags
         ("fsq", "google", or "fsq+google_enriched")
```

### Extract-Place Flow

```
extract_place(raw_input)
  │
  ├── 1. Parse input → extract place name + location hints
  │
  ├── 2. Search FsqLocalProvider by name + location
  │      If confidence > 0.8 → use FSQ match, skip Google
  │
  ├── 3. If no match or low confidence → GooglePlacesProvider
  │
  └── 4. Return validated place with source tag
```

### Key Design Decisions

1. FSQ is always queried first. Google is the fallback, never the primary.
2. Enrichment happens late — only on the 3 final candidates after ranking, not on all 20 discovery results. This keeps Google API calls at 3 per consult max.
3. Source tagging flows through to the consult response (`"discovered_fsq"` vs `"discovered_google"`).
4. The threshold for falling back to Google is configurable in `config/providers.yaml` (e.g., `min_local_candidates: 3`).

### File Structure in totoro-ai

```
src/
  providers/
    place_provider.py      # Protocol + PlaceCandidate model
    fsq_local.py           # FsqLocalProvider
    google_places.py       # GooglePlacesProvider
  services/
    place_discovery.py     # Orchestration logic
  config/
    providers.yaml         # min_local_candidates, enrichment toggle, etc.
```

---

## Google Places API Data: Storage and Caching Rules

Google's Terms of Service restrict what you can persist from Places API responses. This section documents what Totoro can and cannot store.

### What you can store permanently (PostgreSQL)

- **google_place_id** — explicitly exempt from caching restrictions. Store it in fsq_places mapped to fsq_place_id. This lets future enrichment calls use a direct Place Details lookup ($20/1K) instead of a Nearby Search ($32/1K).

### What you can cache short-term (Redis, 1-2 hour TTL)

- Opening hours
- Ratings
- Price level
- Review count

This avoids re-calling Google if the same place shows up in multiple consults within a short window. Redis is already exclusively owned by totoro-ai, so this fits the architecture. Google's enforcement targets persistent database storage, not ephemeral memory caches. The strict reading of their terms says no caching beyond place_id, so this is a conscious tradeoff — low risk, documented here.

### What you never persist

- Hours, ratings, price level, photos — never written to PostgreSQL
- Review text, photo URLs — never stored anywhere
- Any Google Maps Content beyond google_place_id

### How this works in the consult pipeline

1. Ranking picks the top 3 candidates from FSQ local data
2. PlaceDiscoveryService calls Google Place Details for live enrichment (hours, ratings, price)
3. Enriched data is attached to the response object sent to the frontend
4. Redis caches the enrichment keyed by google_place_id with a 1-2 hour TTL
5. NestJS stores the recommendation in the recommendations table with FSQ data only (name, category, location, source). Google-enriched fields are display-only and never persisted.
6. Next time the same place appears as a candidate within the TTL window, Redis serves the cached enrichment. After TTL expires, a fresh Google call is made.
