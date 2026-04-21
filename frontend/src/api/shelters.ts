import { adminAuthHeaders } from './adminToken'

const DEFAULT_API_BASE_URL =
  typeof window === 'undefined' ? 'http://localhost:5173' : ''
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL

export interface ShelterLookupEntity {
  name: string
  aliases: string[]
  entity_type: string
}

export interface ShelterLookupResponse {
  found: boolean
  entity: ShelterLookupEntity | null
}

export interface ShelterCandidate {
  canonical_name: string
  entity_type: string
  address: string
  website: string
  facebook_url: string
  aliases: string[]
  introduction: string
  cover_image_url: string
  evidence_urls: string[]
}

export interface ShelterVerifyResponse {
  verified: boolean
  candidate: ShelterCandidate | null
  reason: string
}

export interface ShelterCreateResponse {
  entity_name: string
  entity_id: number
  created: boolean
  scheduled_first_crawl: boolean
  status: 'created' | 'existing'
}

export async function lookupShelter(query: string): Promise<ShelterLookupResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/entities/lookup?q=${encodeURIComponent(query)}`,
  )
  if (!response.ok) {
    throw new Error(`Lookup failed (${response.status})`)
  }
  return response.json() as Promise<ShelterLookupResponse>
}

export async function verifyShelter(query: string): Promise<ShelterVerifyResponse> {
  const response = await fetch(`${API_BASE_URL}/api/shelters/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
    body: JSON.stringify({ query }),
  })
  if (response.status === 401) {
    throw new Error('ADMIN_TOKEN_REQUIRED')
  }
  if (response.status === 409) {
    throw new Error('SHELTER_ALREADY_EXISTS')
  }
  if (response.status === 503) {
    throw new Error('VERIFICATION_UNAVAILABLE')
  }
  if (!response.ok) {
    throw new Error(`Verification failed (${response.status})`)
  }
  return response.json() as Promise<ShelterVerifyResponse>
}

export async function createShelter(
  candidate: ShelterCandidate,
): Promise<ShelterCreateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/shelters/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
    body: JSON.stringify(candidate),
  })
  if (response.status === 401) {
    throw new Error('ADMIN_TOKEN_REQUIRED')
  }
  if (!response.ok) {
    throw new Error(`Create failed (${response.status})`)
  }
  return response.json() as Promise<ShelterCreateResponse>
}
