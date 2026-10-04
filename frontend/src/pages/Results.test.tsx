import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Results from './Results'
import { ProcessingContext } from '../lib/processing-context'

// `vi.mock` is hoisted above every import, so the stub object has to be built
// through `vi.hoisted` to be in place when the factory runs.
const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    valueFacets: vi.fn(),
    companies: vi.fn(),
    resultsSummary: vi.fn(),
    resultsCoverage: vi.fn(),
    values: vi.fn(),
    updateValue: vi.fn(),
    createValue: vi.fn(),
    startProcessing: vi.fn(),
    stopProcessing: vi.fn(),
    summaryExportUrl: vi.fn(() => '/api/results/summary/export.xlsx'),
  },
}))

vi.mock('../lib/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.name = 'ApiError'
      this.status = status
    }
  },
  api: apiMock,
}))

function cell(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    document_id: 10,
    normalized_value: 100,
    original_value: null,
    confidence: 0.9,
    status: 'OK',
    is_edited: false,
    extraction_method: 'ai',
    page: 1,
    currency: 'IDR',
    ...over,
  }
}

/** One company-year row carrying two figures in a single row. */
function summaryResponse(cells: Record<string, ReturnType<typeof cell>>) {
  return {
    items: [
      {
        company: 'ACME',
        year: 2024,
        currency: 'IDR',
        subsector: 'Food',
        cells,
        documents: [{ id: 10, filename: 'acme-2024.xhtml', statements: ['balance_sheet'] }],
        failed_checks: {},
      },
    ],
    fields: Object.keys(cells),
    labels: {
      total_assets: 'Total assets',
      total_liabilities: 'Total liabilities',
      gross_profit: 'Gross profit',
    },
    currencies: [{ currency: 'IDR', count: 2 }],
    subsectors: [{ subsector: 'Food', count: 2 }],
    pagination: { page: 1, pages: 1, total: 1, page_size: 50 },
  }
}

const TWO_FIGURES = summaryResponse({
  total_assets: cell({ id: 101, normalized_value: 100 }),
  total_liabilities: cell({ id: 102, normalized_value: 200 }),
})

const processing = {
  state: null,
  error: null,
  loading: false,
  initialLoading: false,
  refetch: () => {},
}

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location">{location.search}</span>
}

function renderResults(search = '?view=summary') {
  return render(
    <MemoryRouter initialEntries={[`/results${search}`]}>
      <ProcessingContext.Provider value={processing}>
        <Results />
        <LocationProbe />
      </ProcessingContext.Provider>
    </MemoryRouter>,
  )
}

const openEditor = (label: RegExp) => screen.findByRole('button', { name: label })
const amountInput = () => screen.findByLabelText(/corrected amount/i) as Promise<HTMLInputElement>
// The trigger announces its field and its state together,
// so it is found by role and part of its name, never by
// the visible label alone.
const subsectorTrigger = () =>
  screen.getByRole('button', { name: /sub-sector/i })

beforeEach(() => {
  for (const fn of Object.values(apiMock)) fn.mockReset()
  apiMock.valueFacets.mockResolvedValue({ statements: [], fields: [], years: [], currencies: [] })
  apiMock.companies.mockResolvedValue({ items: [] })
  apiMock.resultsSummary.mockResolvedValue(TWO_FIGURES)
  apiMock.resultsCoverage.mockResolvedValue({
    companies_discovered: 1,
    companies_with_values: 1,
    companies_without_values: 0,
    documents_total: 1,
    documents_with_values: 1,
    missing: [],
  })
  apiMock.updateValue.mockResolvedValue({ value: cell() })
  apiMock.createValue.mockResolvedValue({ value: cell() })
})

describe('Summary grid inline editor', () => {
  it('shows the figure that was clicked, not the one opened before it', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    expect((await amountInput()).value).toBe('100')

    // Open a second figure in the same row while the first editor is still up.
    fireEvent.click(await openEditor(/edit total liabilities for acme 2024/i))

    await waitFor(async () => {
      expect((await amountInput()).value).toBe('200')
    })
  })

  it('saves the correction to the figure that was clicked', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    // Switch to the other figure without typing anything, then save.
    fireEvent.click(await openEditor(/edit total liabilities for acme 2024/i))
    fireEvent.click(await screen.findByRole('button', { name: /save correction/i }))

    // The unedited value of the *clicked* figure must be written to its own row.
    // This wrote the previously-opened figure's amount onto the wrong value.
    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledWith(
        102,
        expect.objectContaining({ normalized_value: 200 }),
      )
    })
  })

  it('keeps a hand-typed correction when switching figures', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    fireEvent.change(await amountInput(), { target: { value: '1234' } })

    fireEvent.click(await openEditor(/edit total liabilities for acme 2024/i))
    fireEvent.click(await screen.findByRole('button', { name: /save correction/i }))

    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledTimes(1)
      expect(apiMock.updateValue).toHaveBeenCalledWith(
        102,
        expect.objectContaining({ normalized_value: 200 }),
      )
    })
  })
})

describe('Filter state in the URL', () => {
  beforeEach(() => {
    // Mocked only so that a regression which calls it fails on the assertion in
    // the last test rather than on an unresolved request.
    apiMock.values.mockResolvedValue({
      items: [],
      pagination: { page: 1, pages: 1, total: 0, page_size: 50 },
    })
  })

  it('does not count the page as a filter', async () => {
    // Page 3 of the grid with nothing filtered. Paging is not a filter, so
    // there is nothing to clear.
    renderResults('?page=3')
    await waitFor(() => expect(apiMock.resultsSummary).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /clear \d+ filters?/i })).toBeNull()
  })

  it('counts only real filters', async () => {
    renderResults(
      '?page=3&company=ACME&year=2024&currency=USD&subsector=Food&profitable=true',
    )
    expect(await screen.findByRole('button', { name: /clear 5 filters/i })).toBeTruthy()
  })

  it('clears the filters and resets the page', async () => {
    renderResults('?page=3&company=ACME&year=2024')
    fireEvent.click(await screen.findByRole('button', { name: /clear 2 filters/i }))

    await waitFor(() => {
      const params = new URLSearchParams(screen.getByTestId('location').textContent ?? '')
      expect(params.get('company')).toBeNull()
      expect(params.get('year')).toBeNull()
      // Page state survives as a concept but is reset here: the result set it
      // was pointing into no longer exists.
      expect(params.get('page')).toBeNull()
    })
  })

  it('never asks for the removed All values list, whatever the URL says', async () => {
    // A stale bookmark or shared link carrying the old tab must not resurrect
    // it: the page is the summary only, and those params are not even tracked.
    renderResults('?view=values&sort=value&order=desc&search=total')
    await waitFor(() => expect(apiMock.resultsSummary).toHaveBeenCalled())
    expect(apiMock.values).not.toHaveBeenCalled()
    expect(screen.queryByRole('tab')).toBeNull()
    expect(screen.queryByRole('button', { name: /clear \d+ filters?/i })).toBeNull()
  })
})

describe('Filter selects on the summary', () => {
  beforeEach(() => {
    apiMock.companies.mockResolvedValue({
      items: [{ company: 'ACME' }, { company: 'AALI Astra Agro Lestari Tbk' }],
    })
    apiMock.valueFacets.mockResolvedValue({
      statements: [],
      fields: [],
      years: [2023, 2024],
      currencies: [],
    })
  })

  const params = () => new URLSearchParams(screen.getByTestId('location').textContent ?? '')
  const choose = (label: RegExp, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } })

  // The option lists arrive from the API, and a <select> silently coerces an
  // unknown value to "", which would look like the filter doing nothing.
  const waitForOption = (label: RegExp, value: string) =>
    waitFor(() => {
      const sel = screen.getByLabelText(label) as HTMLSelectElement
      expect(Array.from(sel.options).map((o) => o.value)).toContain(value)
    })

  it('records the chosen company in the URL and re-queries the summary', async () => {
    renderResults()
    await waitForOption(/^company$/i, 'AALI Astra Agro Lestari Tbk')
    choose(/^company$/i, 'AALI Astra Agro Lestari Tbk')

    await waitFor(() => {
      expect(params().get('company')).toBe('AALI Astra Agro Lestari Tbk')
    })
    // The regression: a second setParam in the same handler re-read the stale
    // search params and overwrote the company with ?page=1.
    expect(params().get('page')).toBeNull()
    expect((screen.getByLabelText(/^company$/i) as HTMLSelectElement).value).toBe(
      'AALI Astra Agro Lestari Tbk',
    )
    expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
      expect.objectContaining({ company: 'AALI Astra Agro Lestari Tbk' }),
    )
  })

  it('leaves no stray parameters when the placeholder is chosen', async () => {
    renderResults('?company=ACME')
    await waitForOption(/^company$/i, 'AALI Astra Agro Lestari Tbk')
    choose(/^company$/i, '')

    await waitFor(() => expect(params().get('company')).toBeNull())
    // "All companies" is not a filter: the URL must go back to bare /results.
    expect(screen.getByTestId('location').textContent).toBe('')
  })

  it('records the year and the currency too, and keeps them together', async () => {
    renderResults()
    await waitForOption(/^year$/i, '2024')
    choose(/^year$/i, '2024')
    await waitFor(() => expect(params().get('year')).toBe('2024'))

    await waitForOption(/^company$/i, 'ACME')
    choose(/^company$/i, 'ACME')
    await waitFor(() => expect(params().get('company')).toBe('ACME'))

    await waitForOption(/^currency$/i, 'IDR')
    choose(/^currency$/i, 'IDR')
    await waitFor(() => expect(params().get('currency')).toBe('IDR'))

    // Each one is a separate navigation, so none of them may clobber another.
    expect(params().get('year')).toBe('2024')
    expect(params().get('company')).toBe('ACME')
    expect(params().get('page')).toBeNull()
    expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
      expect.objectContaining({ company: 'ACME', year: '2024', currency: 'IDR' }),
    )
  })

  it('resets the page number when a filter changes', async () => {
    apiMock.resultsSummary.mockResolvedValue({
      ...TWO_FIGURES,
      pagination: { page: 1, pages: 3, total: 120, page_size: 50 },
    })
    renderResults('?page=3')
    await waitFor(() => expect(apiMock.resultsSummary).toHaveBeenCalled())
    choose(/^company$/i, 'ACME')

    // Page 3 of a narrower result set would render empty, so it is dropped.
    await waitFor(() => expect(params().get('page')).toBeNull())
    expect(params().get('company')).toBe('ACME')
  })

  it('records the chosen sub-sector in the URL and re-queries the summary', async () => {
    renderResults()
    fireEvent.click(subsectorTrigger())
    fireEvent.click(await screen.findByLabelText(/^food \(2\)$/i))

    await waitFor(() => {
      expect(params().getAll('subsector')).toEqual(['Food'])
    })
    expect(params().get('page')).toBeNull()
    await waitFor(() =>
      expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ subsector: ['Food'] }),
      ),
    )
  })

  it('lets several sub-sectors be selected at once', async () => {
    apiMock.resultsSummary.mockResolvedValue({
      ...TWO_FIGURES,
      subsectors: [
        { subsector: 'Food', count: 1 },
        { subsector: 'Beverage', count: 1 },
      ],
    })
    renderResults()
    // One visit to the list: it stays open while options are
    // ticked, which is the point of picking several.
    fireEvent.click(subsectorTrigger())
    fireEvent.click(await screen.findByLabelText(/^food \(1\)$/i))
    fireEvent.click(screen.getByLabelText(/^beverage \(1\)$/i))

    await waitFor(() => {
      expect(params().getAll('subsector')).toEqual(['Food', 'Beverage'])
    })
    await waitFor(() =>
      expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ subsector: ['Food', 'Beverage'] }),
      ),
    )

    // Unticking one leaves the other in force.
    fireEvent.click(screen.getByLabelText(/^food \(1\)$/i))
    await waitFor(() => {
      expect(params().getAll('subsector')).toEqual(['Beverage'])
    })
  })

  it('names the chosen sub-sector on the closed control', async () => {
    renderResults()
    fireEvent.click(subsectorTrigger())
    fireEvent.click(await screen.findByLabelText(/^food \(2\)$/i))

    // The control reports what is in force without being opened,
    // the way a select shows its value -- field name and
    // selection together.
    expect(
      await screen.findByRole('button', { name: /sub-sector food/i }),
    ).toBeTruthy()
  })

  it('clears every chosen sub-sector from the control', async () => {
    renderResults()
    fireEvent.click(subsectorTrigger())
    fireEvent.click(await screen.findByLabelText(/^food \(2\)$/i))
    await waitFor(() => expect(params().get('subsector')).toBe('Food'))

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))

    await waitFor(() => {
      expect(params().getAll('subsector')).toEqual([])
    })
    expect(
      screen.getByRole('button', { name: /sub-sector all sub-sectors/i }),
    ).toBeTruthy()
  })

  it('closes the sub-sector list when the reader clicks elsewhere', async () => {
    renderResults()
    fireEvent.click(subsectorTrigger())
    expect(await screen.findByLabelText(/^food \(2\)$/i)).toBeTruthy()

    fireEvent.mouseDown(document.body)

    expect(screen.queryByLabelText(/^food \(2\)$/i)).toBeNull()
  })

  it('labels the undeclared bucket so it reads as its own filter', async () => {
    apiMock.resultsSummary.mockResolvedValue({
      ...TWO_FIGURES,
      subsectors: [
        { subsector: 'Food', count: 1 },
        { subsector: 'none', count: 1 },
      ],
    })
    renderResults()
    fireEvent.click(subsectorTrigger())
    expect(
      await screen.findByLabelText(/^no sub-sector declared \(1\)$/i),
    ).toBeTruthy()
  })

  it('records the no-net-loss filter as a URL flag and re-queries', async () => {
    renderResults()
    fireEvent.click(screen.getByLabelText(/^no net loss$/i))

    await waitFor(() => {
      expect(params().get('profitable')).toBe('true')
    })
    expect(params().get('page')).toBeNull()
    await waitFor(() =>
      expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ profitable: 'true' }),
      ),
    )

    // Switching it off must take the flag back out of the URL, or the
    // grid would stay narrowed after the box was unticked.
    fireEvent.click(screen.getByLabelText(/^no net loss$/i))
    await waitFor(() => expect(params().get('profitable')).toBeNull())
  })

  it('re-queries when the sub-sector filter changes, not just the other filters', async () => {
    renderResults('?subsector=Food')
    await waitFor(() => expect(apiMock.resultsSummary).toHaveBeenCalled())
    expect(apiMock.resultsSummary).toHaveBeenLastCalledWith(
      expect.objectContaining({ subsector: ['Food'] }),
    )
  })
})

describe('Amount entry', () => {
  it('accepts a stored figure that has cents', async () => {
    // BOBA 2021 gross_profit, verbatim: a real row the extractor read as
    // 31,635,083,104.74. It was uneditable while the parser rejected decimals.
    apiMock.resultsSummary.mockResolvedValue(
      summaryResponse({
        gross_profit: cell({ id: 303, normalized_value: 31_635_083_104.74 }),
      }),
    )
    renderResults()
    fireEvent.click(await openEditor(/edit gross profit for acme 2024/i))

    const input = await amountInput()
    expect(input.value).toBe('31635083104.74')
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledWith(
        303,
        expect.objectContaining({ normalized_value: 31_635_083_104.74 }),
      )
    })
  })

  it('saves an edited fractional figure', async () => {
    apiMock.resultsSummary.mockResolvedValue(
      summaryResponse({
        gross_profit: cell({ id: 303, normalized_value: 31_635_083_104.74 }),
      }),
    )
    renderResults()
    fireEvent.click(await openEditor(/edit gross profit for acme 2024/i))

    fireEvent.change(await amountInput(), { target: { value: '31635083104.5' } })
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledWith(
        303,
        expect.objectContaining({ normalized_value: 31_635_083_104.5 }),
      )
    })
  })

  it('reads commas as thousands separators, not as a decimal mark', async () => {
    apiMock.resultsSummary.mockResolvedValue(
      summaryResponse({
        gross_profit: cell({ id: 303, normalized_value: 31_635_083_104.74 }),
      }),
    )
    renderResults()
    fireEvent.click(await openEditor(/edit gross profit for acme 2024/i))

    fireEvent.change(await amountInput(), { target: { value: '31,635,083,104' } })
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledWith(
        303,
        expect.objectContaining({ normalized_value: 31_635_083_104 }),
      )
    })
  })

  it('clears a figure to null when the field is emptied', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    fireEvent.change(await amountInput(), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    await waitFor(() => {
      expect(apiMock.updateValue).toHaveBeenCalledTimes(1)
      const [, body] = apiMock.updateValue.mock.calls[0]
      // NaN is the sentinel for "this figure is not present". The api layer
      // serialises it, and JSON.stringify turns NaN into the null the backend
      // stores -- which is why the sentinel is safe to pass through.
      expect(Number.isNaN(body.normalized_value)).toBe(true)
      expect(JSON.parse(JSON.stringify(body)).normalized_value).toBeNull()
    })
  })

  it('still rejects text that is not a number', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    fireEvent.change(await amountInput(), { target: { value: '1.2.3' } })
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    expect(await screen.findByText(/optional decimal part/i)).toBeTruthy()
    expect(apiMock.updateValue).not.toHaveBeenCalled()
  })

  it('rejects a value past the safe integer range', async () => {
    renderResults()
    fireEvent.click(await openEditor(/edit total assets for acme 2024/i))
    fireEvent.change(await amountInput(), { target: { value: '9'.repeat(400) } })
    fireEvent.click(screen.getByRole('button', { name: /save correction/i }))

    expect(await screen.findByText(/too large to be stored safely/i)).toBeTruthy()
    expect(apiMock.updateValue).not.toHaveBeenCalled()
  })
})