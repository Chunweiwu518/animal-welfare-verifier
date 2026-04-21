const DEFAULT_API_BASE_URL =
  typeof window === 'undefined' ? 'http://localhost:5173' : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

export interface ReviewRatingSummary {
  avg_score: number | null
  count: number
  mine: number | null
}

export interface EntityCredibility {
  entity_name: string
  score: number | null
  reviews_rated: number
  total_ratings: number
  breakdown: {
    supporting_weight: number
    opposing_weight: number
    neutral_weight: number
  }
}

async function jsonRequest<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (response.status === 401) {
    throw new Error('LOGIN_REQUIRED')
  }
  if (!response.ok) {
    throw new Error(`request failed (${response.status})`)
  }
  return (await response.json()) as T
}

export async function rateReview(reviewId: number, score: number): Promise<void> {
  await jsonRequest(`${API_BASE_URL}/api/reviews/${reviewId}/rating`, {
    method: 'POST',
    body: JSON.stringify({ score }),
  })
}

export async function removeReviewRating(reviewId: number): Promise<void> {
  await jsonRequest(`${API_BASE_URL}/api/reviews/${reviewId}/rating`, {
    method: 'DELETE',
  })
}

export async function getReviewRatingSummary(reviewId: number): Promise<ReviewRatingSummary> {
  return jsonRequest(`${API_BASE_URL}/api/reviews/${reviewId}/rating-summary`)
}

export async function flagReviewIrrelevant(reviewId: number): Promise<void> {
  await jsonRequest(`${API_BASE_URL}/api/reviews/${reviewId}/react`, {
    method: 'POST',
    body: JSON.stringify({ reaction: 'irrelevant' }),
  })
}

export async function getEntityCredibility(entityName: string): Promise<EntityCredibility> {
  const response = await fetch(
    `${API_BASE_URL}/api/entities/${encodeURIComponent(entityName)}/credibility`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(`credibility fetch failed (${response.status})`)
  }
  return (await response.json()) as EntityCredibility
}
