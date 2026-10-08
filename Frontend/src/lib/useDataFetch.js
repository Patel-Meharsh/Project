import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * Shared hook for fetching data on mount with loading/error states.
 *
 * @param {Function} fetcher  — async function returning the data (called once on mount)
 * @param {Array}    deps     — extra dependencies to re-trigger the fetch (default [])
 * @returns {{ data, loading, error, refetch }}
 *
 * Usage:
 *   const { data, loading, error, refetch } = useDataFetch(() =>
 *     Promise.all([prApi.getAll(), itemApi.getAll()])
 *   )
 *   // data = [prs, items] once resolved
 */
export default function useDataFetch(fetcher, deps = []) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const mountedRef            = useRef(true)

  const run = useCallback(() => {
    setLoading(true)
    setError(null)
    fetcher()
      .then(result => { if (mountedRef.current) { setData(result); setLoading(false) } })
      .catch(err   => { if (mountedRef.current) { setError(err);   setLoading(false) } })
  }, deps)  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    mountedRef.current = true
    run()
    return () => { mountedRef.current = false }
  }, [run])

  return { data, loading, error, refetch: run }
}
