import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CompanyDetail from './CompanyDetail'
import { ProcessingContext } from '../lib/processing-context'

// `vi.mock` is hoisted above every import, so the stub object has to be
// built through `vi.hoisted` to be in place when the factory runs.
const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    companyProfile: vi.fn(),
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

/** Values in rupiah, spanning the magnitudes real filings carry, so
 *  the compact formatter and the exact table can both be asserted. */
const POINT = (year: number, value: number | null, over = {}) => ({
  year,
  normalized_value: value,
  currency: 'IDR',
  status: 'OK',
  document_id: year === 2023 ? 1 : 2,
  page: 5,
  ...over,
})

function profileResponse(over: Record<string, unknown> = {}) {
  return {
    company: 'PT AAA Tbk',
    years: [2023, 2024],
    currencies: ['IDR'],
    totals: {
      documents: 2,
      documents_with_values: 2,
      figures: 10,
      years: 2,
      fields: 8,
    },
    metrics: {
      total_assets: [
        POINT(2023, 900_000_000_000),
        POINT(2024, 1_250_000_000_000),
      ],
      total_equity: [
        POINT(2023, 500_000_000_000),
        POINT(2024, 600_000_000_000),
      ],
      equity_attributable_to_owners_of_parent: [
        POINT(2024, 550_000_000_000),
      ],
      non_controlling_interest: [POINT(2024, 50_000_000_000)],
      sales_and_revenue: [
        POINT(2023, 700_000_000_000),
        POINT(2024, 800_000_000_000),
      ],
      total_profit_loss: [
        POINT(2023, -50_000_000_000),
        POINT(2024, 100_000_000_000),
      ],
      income_tax_paid_operating: [POINT(2024, -24_000_000_000)],
      // The classification is a property of the company, not of a
      // year; it rides on text_value.
      sub_sector: [
        POINT(2024, null, { text_value: 'D2. Food & Beverage' }),
      ],
    },
    quality: {
      figures: 10,
      disputed_cells: 0,
      flagged_cells: 0,
      cells_without_currency: 0,
      failed_checks: {},
      disputed_fields: [],
    },
    documents: [
      {
        id: 1,
        filename: 'aaa-2023.xhtml',
        file_path: '',
        status: 'COMPLETED',
        pdf_type: 'html',
        pages: 100,
        reporting_year: 2023,
        values: 5,
        years: [2023],
      },
      {
        id: 2,
        filename: 'aaa-2024.xhtml',
        file_path: '',
        status: 'COMPLETED',
        pdf_type: 'html',
        pages: 110,
        reporting_year: 2024,
        values: 5,
        years: [2024],
      },
    ],
    labels: {},
    ...over,
  }
}

const processing = {
  state: null,
  error: null,
  loading: false,
  initialLoading: false,
  refetch: () => {},
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/companies/PT%20AAA%20Tbk']}>
      <ProcessingContext.Provider value={processing}>
        <CompanyDetail />
      </ProcessingContext.Provider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  apiMock.companyProfile.mockReset()
  apiMock.companyProfile.mockResolvedValue(profileResponse())
})

describe('CompanyDetail', () => {
  it('names the entity and shows its declared sub-sector', async () => {
    renderDetail()
    expect(await screen.findByText('PT AAA Tbk')).toBeTruthy()
    // The sub-sector is a property of the company, shown as itself
    // rather than dressed up as a financial KPI.
    expect(await screen.findByText('Subsektor')).toBeTruthy()
    expect(screen.getByText('D2. Food & Beverage')).toBeTruthy()
  })

  it('leads with the four core indicators, compactly', async () => {
    renderDetail()
    // Each name is also a row in the Ikhtisar table below,
    // so several matches are the expected outcome.
    for (const label of [
      'Jumlah Aset',
      'Jumlah Ekuitas',
      'Penjualan dan Pendapatan Usaha',
      'Jumlah Laba (Rugi)',
    ]) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0)
    }
    // 1,25 T / 600 M / 800 M / 100 M
    expect(await screen.findByText('Rp 1,25 T')).toBeTruthy()
    expect(screen.getByText('Rp 600 M')).toBeTruthy()
    expect(screen.getByText('Rp 800 M')).toBeTruthy()
    expect(screen.getByText('Rp 100 M')).toBeTruthy()
  })

  it('shows the change against the previous reporting year', async () => {
    renderDetail()
    // (1,25 T - 900 M) / 900 M
    expect(
      await screen.findByText('+38,89% dari tahun lalu'),
    ).toBeTruthy()
    // A profit year after a loss year is an event, not a
    // percentage: the base is negative.
    expect(
      screen.getByText('kembali laba dari tahun lalu'),
    ).toBeTruthy()
  })

  it('connects the equity composition to the total', async () => {
    renderDetail()
    // The composition and the Ikhtisar table both name the
    // parts, so several matches are expected.
    expect(
      (await screen.findAllByText('Ekuitas Pemilik Entitas Induk')).length,
    ).toBeGreaterThan(0)
    expect(
      (await screen.findAllByText('Kepentingan Non Pengendali')).length,
    ).toBeGreaterThan(0)
    // The composition shows the exact figures, not the
    // compact ones the KPI cards use.
    expect(
      (await screen.findAllByText('550.000.000.000')).length,
    ).toBeGreaterThan(0)
    expect(
      (await screen.findAllByText('50.000.000.000')).length,
    ).toBeGreaterThan(0)
  })

  it('labels a tax outflow as a payment by its sign', async () => {
    renderDetail()
    expect(await screen.findByText('Rp (24 M)')).toBeTruthy()
    expect(
      screen.getByText('Pembayaran pajak penghasilan'),
    ).toBeTruthy()
  })

  it('charts the trend with an accessible summary', async () => {
    renderDetail()
    expect(
      await screen.findByRole('img', {
        name: /Penjualan dan Pendapatan Usaha.*Jumlah Laba \(Rugi\) per tahun/,
      }),
    ).toBeTruthy()
  })

  it('keeps every digit in the Ikhtisar Keuangan table', async () => {
    renderDetail()
    // The table is the detail view: no scaling, no rounding.
    // The balance-sheet card prints the same digits, so
    // several matches are expected.
    expect(
      (await screen.findAllByText('1.250.000.000.000')).length,
    ).toBeGreaterThan(0)
    // A loss prints in parentheses, with all its digits.
    expect(screen.getByText('(50.000.000.000)')).toBeTruthy()
    // The Perubahan column carries the same short change.
    expect(screen.getByText('+38,89%')).toBeTruthy()
  })

  it('traces a figure to its source document and page', async () => {
    renderDetail()
    // The filings table lists the same report, so several
    // matches are expected.
    expect(
      (await screen.findAllByText('aaa-2024.xhtml')).length,
    ).toBeGreaterThan(0)
    // Every KPI card carries its own source line, so
    // several matches are expected.
    expect(
      screen.getAllByText(/Halaman 5/).length,
    ).toBeGreaterThan(0)
  })

  it('drops an indicator the company never reported', async () => {
    // A Record, so the key can be removed: the inferred object
    // type would call it required, and `delete` refuses.
    const metrics: Record<string, unknown> = {
      ...profileResponse().metrics,
    }
    delete metrics.non_controlling_interest
    apiMock.companyProfile.mockResolvedValue(
      profileResponse({ metrics }),
    )
    renderDetail()
    expect(
      (await screen.findAllByText('Jumlah Aset')).length,
    ).toBeGreaterThan(0)
    // No half is invented: the composition shows the parent
    // against the total, and the table drops the row entirely.
    expect(
      screen.queryByText('Kepentingan Non Pengendali'),
    ).not.toBeTruthy()
  })

  it('says the figures are missing when the company has none', async () => {
    apiMock.companyProfile.mockResolvedValue(
      profileResponse({
        years: [],
        metrics: {},
        totals: {
          documents: 1,
          documents_with_values: 0,
          figures: 0,
          years: 0,
          fields: 0,
        },
      }),
    )
    renderDetail()
    expect(
      await screen.findByText('Belum ada angka keuangan'),
    ).toBeTruthy()
  })
})
