-- Re-run this file to restore seed data after wiping tables.
-- Assumes the schema from 001_initial_schema.sql is already applied.

INSERT INTO agencies (name, industry) VALUES
  ('TechStaff Pro', 'Technology'),
  ('HealthFirst Staffing', 'Healthcare')
ON CONFLICT DO NOTHING;

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
FROM agencies WHERE name = 'TechStaff Pro'
ON CONFLICT DO NOTHING;
