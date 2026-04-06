# Data Model: Extraction Cascade Run 2

> All types below already exist in `types.py` (Run 1). This document describes their
> relationships and how they flow through the new Run 2 components.

## Core Types (unchanged from Run 1)

### `ExtractionLevel` (enum)
| Member | Value | Priority Index | Notes |
|---|---|---|---|
| `EMOJI_REGEX` | `"emoji_regex"` | 0 | Highest priority |
| `LLM_NER` | `"llm_ner"` | 1 | |
| `SUBTITLE_CHECK` | `"subtitle_check"` | 2 | |
| `WHISPER_AUDIO` | `"whisper_audio"` | 3 | |
| `VISION_FRAMES` | `"vision_frames"` | 4 | Lowest priority |

### `CandidatePlace` (dataclass)
| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Raw name from enricher |
| `city` | `str \| None` | Optional location hint |
| `cuisine` | `str \| None` | Optional cuisine type |
| `source` | `ExtractionLevel` | Which enricher produced this |
| `corroborated` | `bool` | Set to `True` by `dedup_candidates` when two enrichers agreed |

### `ExtractionContext` (dataclass, mutable shared state)
| Field | Type | Notes |
|---|---|---|
| `url` | `str \| None` | Source URL; `None` for plain-text inputs |
| `user_id` | `str` | Scopes the extraction run |
| `supplementary_text` | `str` | Caption or user-supplied text |
| `caption` | `str \| None` | First-write-wins; oEmbed enricher sets this |
| `transcript` | `str \| None` | First-write-wins; `SubtitleCheckEnricher` sets this before Whisper runs |
| `candidates` | `list[CandidatePlace]` | Append-only during enrichment; deduped after |
| `pending_levels` | `list[ExtractionLevel]` | Set by `ExtractionPipeline` when Phase 3 fires |

### `ExtractionResult` (dataclass, output of validation)
| Field | Type | Notes |
|---|---|---|
| `place_name` | `str` | Validated name from Google Places (or candidate name if none returned) |
| `address` | `str \| None` | From Google Places |
| `city` | `str \| None` | From candidate |
| `cuisine` | `str \| None` | From candidate |
| `confidence` | `float` | In range `[0.0, config.max_score]` |
| `resolved_by` | `ExtractionLevel` | Source enricher level |
| `corroborated` | `bool` | Whether candidate had multiple agreeing enrichers |
| `external_provider` | `str \| None` | `"google"` for `GooglePlacesClient` |
| `external_id` | `str \| None` | Google Place ID; `None` means validation failed |

### `ProvisionalResponse` (dataclass, Phase 3 return)
| Field | Type | Notes |
|---|---|---|
| `extraction_status` | `str` | `"processing"` |
| `confidence` | `float` | `0.0` |
| `message` | `str` | Human-readable status |
| `pending_levels` | `list[ExtractionLevel]` | The three background levels |

### `ExtractionPending` (dataclass + event) — **Run 2 addition: `event_type` field**
| Field | Type | Notes |
|---|---|---|
| `user_id` | `str` | |
| `url` | `str \| None` | |
| `pending_levels` | `list[ExtractionLevel]` | |
| `context` | `ExtractionContext` | Full shared state passed to background handler |
| `event_type` | `str` | `"extraction_pending"` — **added in Run 2** to enable dispatcher registry lookup |

## New Component Interfaces

### `PlacesValidatorProtocol` (Protocol)
```
validate(candidates: list[CandidatePlace]) -> list[ExtractionResult] | None
```
Returns `None` when candidates is empty or all fail validation. Returns non-empty list on success.

### `GroqTranscriptionProtocol` (Protocol)
```
transcribe_url(cdn_url: str) -> str
transcribe_bytes(audio_bytes: bytes, filename: str) -> str
```

## Confidence Scoring Formula (`calculate_confidence` — already in Run 1)

```
confidence = min((base_score × match_modifier) + corroboration_bonus, max_score)
```

| Source Level | Base Score |
|---|---|
| `EMOJI_REGEX` | 0.95 |
| `LLM_NER` | 0.80 |
| `SUBTITLE_CHECK` | 0.75 |
| `WHISPER_AUDIO` | 0.65 |
| `VISION_FRAMES` | 0.55 |

| Match Quality | Modifier |
|---|---|
| `EXACT` | 1.0 |
| `FUZZY` | 0.9 |
| `CATEGORY_ONLY` | 0.8 |
| `NONE` | 0.3 |

- Corroboration bonus: `+0.10`
- Max score cap: `0.97`

## State Transitions: Three-Phase Pipeline

```
ExtractionContext (url, user_id, text)
       │
       ▼
Phase 1: EnrichmentPipeline
  ├── EmojiRegexEnricher    → appends CandidatePlaces (level: EMOJI_REGEX)
  ├── LLMNEREnricher        → appends CandidatePlaces (level: LLM_NER)
  ├── TikTokOEmbedEnricher  → sets context.caption
  ├── YtDlpMetadataEnricher → sets context.caption (if not set)
  └── dedup_candidates      → collapses same-name candidates, sets corroborated=True
       │
       ▼
Phase 2: GooglePlacesValidator
  └── validate(context.candidates)
       ├── Found: list[ExtractionResult] ──────────────────────────→ RETURN immediately
       └── Empty: None
                │
                ▼
Phase 3: Dispatch
  ├── ExtractionPipeline sets context.pending_levels
  ├── Dispatches ExtractionPending event
  └── Returns ProvisionalResponse
         │
         ▼ (background, via EventDispatcher)
ExtractionPendingHandler.handle(ExtractionPending)
  ├── SubtitleCheckEnricher → sets context.transcript, appends candidates
  ├── WhisperAudioEnricher  → (skips if transcript set), appends candidates
  ├── VisionFramesEnricher  → appends candidates
  ├── dedup_candidates
  ├── GooglePlacesValidator
  └── persistence.save_and_emit(results, user_id)  [TODO: Run 3]
```
