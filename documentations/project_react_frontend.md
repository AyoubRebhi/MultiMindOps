---
name: React frontend architecture
description: React frontend built for the DevSecOps AI Platform to replace Streamlit
type: project
---

A complete React + Vite + TypeScript + Tailwind CSS frontend was built in `frontend-React/`.

**Why:** Replace Streamlit for better UX, scalability, and maintainability.

**How to apply:** When touching the frontend, all source lives in `frontend-React/src/`. The backend API base is `http://localhost:8000`. The Vite proxy rewrites `/api/*` → backend.

Key decisions:
- TanStack Query for data fetching + caching
- Zustand (persisted) for sidebar state + new-task wizard state
- `useTaskPolling` hook polls GET /tasks/:id every 3s until terminal status
- Multi-step new-task wizard: form → plan-preview → generating (poll) → auto-redirect to TaskDetail
- Human review flow handled inside TaskDetail page via POST /tasks/:id/review
- CORS was added to `backend/app/core/app_factory.py` for localhost:3000
