import { Suspense, lazy, useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { Card, Loading, PageHeader } from './components/ui'

/* Pages are split per route. The dashboard is the landing page so it stays in
   the main chunk; everything else is fetched when first visited, which keeps
   the initial download small without a visible delay on navigation. */
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Documents = lazy(() => import('./pages/Documents'))
const DocumentDetail = lazy(() => import('./pages/DocumentDetail'))
const Validations = lazy(() => import('./pages/Validations'))
const Values = lazy(() => import('./pages/Values'))
const Results = lazy(() => import('./pages/Results'))
const CompanyDetail = lazy(() => import('./pages/CompanyDetail'))
const Exports = lazy(() => import('./pages/Exports'))

function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" subtitle="That route does not exist in this dashboard." />
      <Card>
        <p className="text-sm text-muted-foreground">
          Check the address, or pick a destination from the navigation.
        </p>
      </Card>
    </>
  )
}

/** Reset scroll on navigation: the tables are long, and carrying the previous
 *  scroll offset into a new route lands the user mid-table. */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route element={<AppShell />}>
          <Route
            index
            element={
              <Suspense fallback={<Loading label="Loading dashboard." />}>
                <Dashboard />
              </Suspense>
            }
          />
          <Route
            path="documents"
            element={
              <Suspense fallback={<Loading />}>
                <Documents />
              </Suspense>
            }
          />
          <Route
            path="documents/:docId"
            element={
              <Suspense fallback={<Loading label="Loading document." />}>
                <DocumentDetail />
              </Suspense>
            }
          />
          <Route
            path="validations"
            element={
              <Suspense fallback={<Loading />}>
                <Validations />
              </Suspense>
            }
          />
          <Route
            path="values"
            element={
              <Suspense fallback={<Loading />}>
                <Values />
              </Suspense>
            }
          />
          <Route
            path="results"
            element={
              <Suspense fallback={<Loading />}>
                <Results />
              </Suspense>
            }
          />
          <Route
            path="companies/:company"
            element={
              <Suspense fallback={<Loading />}>
                <CompanyDetail />
              </Suspense>
            }
          />
          <Route
            path="exports"
            element={
              <Suspense fallback={<Loading />}>
                <Exports />
              </Suspense>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </>
  )
}