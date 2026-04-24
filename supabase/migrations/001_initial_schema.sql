-- ── Tables ────────────────────────────────────────────────────────────────────

CREATE TABLE agencies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  industry TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agency_id UUID REFERENCES agencies(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  required_skills TEXT[] DEFAULT '{}',
  screening_questions JSONB DEFAULT '[]',
  interviewer_tone TEXT DEFAULT 'professional',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE candidates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE interviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
  candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
  status TEXT DEFAULT 'pending',
  transcript JSONB DEFAULT '[]',
  scorecard JSONB DEFAULT '{}',
  recording_url TEXT,
  interviewer_name TEXT DEFAULT 'Maya',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  interview_id UUID REFERENCES interviews(id) ON DELETE CASCADE,
  dimension TEXT NOT NULL,
  score INTEGER CHECK (score >= 1 AND score <= 10),
  reasoning TEXT,
  overall_score INTEGER,
  hire_recommendation BOOLEAN,
  summary TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX idx_jobs_agency_id ON jobs(agency_id);
CREATE INDEX idx_interviews_job_id ON interviews(job_id);
CREATE INDEX idx_interviews_candidate_id ON interviews(candidate_id);
CREATE INDEX idx_scores_interview_id ON scores(interview_id);

-- ── Row Level Security ────────────────────────────────────────────────────────

ALTER TABLE agencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE interviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;

-- ── Seed Data ─────────────────────────────────────────────────────────────────

INSERT INTO agencies (name, industry) VALUES
  ('TechStaff Pro', 'Technology'),
  ('HealthFirst Staffing', 'Healthcare');

INSERT INTO jobs (agency_id, title, description, required_skills, screening_questions)
SELECT
  id,
  'Senior Software Engineer',
  'We are looking for a senior engineer to join a fast-growing startup.',
  ARRAY['Python', 'React', 'PostgreSQL'],
  '[
    {"question": "Tell me about your most recent project.", "weight": 2},
    {"question": "How do you handle tight deadlines?", "weight": 1},
    {"question": "What is your availability to start?", "weight": 1}
  ]'::jsonb
FROM agencies WHERE name = 'TechStaff Pro';
