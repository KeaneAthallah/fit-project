import { describe, expect, it } from 'vitest'
import {
  bytes,
  compactRupiah,
  currencyLabel,
  currencyOptions,
  dec,
  deltaShort,
  deltaText,
  duration,
  formatDateID,
  num,
  pct,
  rupiah,
  titleCase,
} from './format'

describe('num / rupiah / dec', () => {
  it('keeps every digit instead of rounding a scanned figure', () => {
    expect(num(1_286_605_455.8)).toBe('1.286.605.455,8')
    expect(rupiah(31_635_083_104.74)).toBe('31.635.083.104,74')
  })

  it('falls back rather than printing NaN', () => {
    expect(num(null)).toBe('—')
    expect(num(undefined)).toBe('—')
    expect(num(Number.NaN)).toBe('—')
    expect(rupiah(null)).toBe('—')
    expect(dec(Number.NaN)).toBe('—')
  })

  it('always shows two decimals for dec', () => {
    expect(dec(1234.5)).toBe('1.234,50')
  })
})

describe('pct', () => {
  // The API returns avg_confidence as a ratio (0.8367), not as 83.67.
  it('scales a ratio, which is the contract the API actually sends', () => {
    expect(pct(0.8367)).toBe('83.7%')
    expect(pct(0.5, 0)).toBe('50%')
    expect(pct(1)).toBe('100.0%')
  })

  it('falls back rather than printing NaN%', () => {
    expect(pct(null)).toBe('—')
    expect(pct(Number.NaN)).toBe('—')
  })
})

describe('duration', () => {
  it('keeps one decimal below a minute', () => {
    expect(duration(0)).toBe('0.0s')
    expect(duration(9.4)).toBe('9.4s')
    expect(duration(59.94)).toBe('59.9s')
  })

  it('carries a rounded second into the next minute instead of printing 60s', () => {
    expect(duration(59.96)).toBe('1m 0s')
    expect(duration(60)).toBe('1m 0s')
    expect(duration(119.4)).toBe('1m 59s')
    // Used to render as "1m 60s".
    expect(duration(119.6)).toBe('2m 0s')
    expect(duration(3599.7)).toBe('1h 0m')
  })

  it('rolls over into hours', () => {
    expect(duration(3600)).toBe('1h 0m')
    expect(duration(7325)).toBe('2h 2m')
  })

  it('falls back rather than printing NaNs', () => {
    expect(duration(null)).toBe('—')
    expect(duration(Number.NaN)).toBe('—')
  })
})

describe('bytes', () => {
  it('steps up a unit at each boundary', () => {
    expect(bytes(900)).toBe('900 B')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(bytes(5_000_000)).toBe('4.8 MB')
    // Used to render as "1024.0 MB" and "5120.0 MB".
    expect(bytes(1024 ** 3)).toBe('1.0 GB')
    expect(bytes(1024 ** 3 * 2)).toBe('2.0 GB')
    expect(bytes(1024 ** 4)).toBe('1024.0 GB')
  })
})

describe('compactRupiah', () => {
  it('scales to the Indonesian units a reader scans', () => {
    expect(compactRupiah(12_450_000_000_000)).toBe('Rp 12,45 T')
    expect(compactRupiah(850_200_000_000)).toBe('Rp 850,2 M')
    expect(compactRupiah(425_700_000)).toBe('Rp 425,7 Jt')
    // A round figure does not carry padded zeros.
    expect(compactRupiah(1_000_000_000_000)).toBe('Rp 1 T')
    expect(compactRupiah(950)).toBe('Rp 950')
  })

  it('puts a loss in parentheses, the way the statements print it', () => {
    expect(compactRupiah(-245_600_000_000)).toBe('Rp (245,6 M)')
    expect(compactRupiah(-500)).toBe('Rp (500)')
  })

  it('keeps zero and falls back rather than inventing a figure', () => {
    expect(compactRupiah(0)).toBe('Rp 0')
    expect(compactRupiah(null)).toBe('—')
    expect(compactRupiah(undefined)).toBe('—')
    expect(compactRupiah(Number.NaN)).toBe('—')
  })
})

describe('deltaText / deltaShort', () => {
  it('reads the change against the previous year', () => {
    expect(deltaText(1_080, 1_000)).toEqual({
      text: '+8% dari tahun lalu',
      tone: 'up',
    })
    expect(deltaText(900, 1_000)?.tone).toBe('down')
    expect(deltaText(900, 1_000)?.text).toBe('-10% dari tahun lalu')
    expect(deltaText(1_000, 1_000)?.tone).toBe('flat')
  })

  it('reports a state instead of a percentage when the base is a loss', () => {
    // A percentage change out of a loss computes to nonsense,
    // so the reader gets the event instead.
    expect(deltaText(100, -50)).toEqual({
      text: 'kembali laba dari tahun lalu',
      tone: 'up',
    })
    expect(deltaText(-80, -50)?.text).toBe('rugi melebar dari tahun lalu')
    expect(deltaText(-20, -50)?.text).toBe('rugi menyusut dari tahun lalu')
  })

  it('says nothing when either year is missing', () => {
    expect(deltaText(100, null)).toBeNull()
    expect(deltaText(null, 100)).toBeNull()
    expect(deltaText(undefined, 100)).toBeNull()
    expect(deltaShort(100, undefined)).toBeNull()
  })

  it('shortens for a table cell, keeping the tone', () => {
    expect(deltaShort(1_080, 1_000)).toEqual({ text: '+8%', tone: 'up' })
    expect(deltaShort(100, -50)).toEqual({ text: 'kembali laba', tone: 'up' })
    expect(deltaShort(-80, -50)?.text).toBe('rugi melebar')
    expect(deltaShort(-80, -50)?.tone).toBe('down')
  })
})

describe('currencyLabel', () => {
  it('spells out the code and keeps "not detected" distinct from IDR', () => {
    expect(currencyLabel('IDR')).toBe('IDR — Rupiah')
    expect(currencyLabel('USD')).toBe('USD — Dolar AS ($)')
    expect(currencyLabel('none')).toBe('Tidak terdeteksi')
    expect(currencyLabel(null)).toBe('—')
    expect(currencyLabel('XYZ')).toBe('XYZ')
  })
})

describe('titleCase', () => {
  it('turns a field name into a heading', () => {
    expect(titleCase('total_liabilities_and_equity')).toBe('Total Liabilities And Equity')
  })
})

describe('formatDateID', () => {
  it('prints the Indonesian day/month/year order', () => {
    expect(formatDateID('1997-12-09')).toBe('09/12/1997')
    expect(formatDateID('2022-08-04')).toBe('04/08/2022')
  })

  it('zero-pads single digits', () => {
    expect(formatDateID('2020-01-05')).toBe('05/01/2020')
  })

  it('falls back to empty rather than printing a guess', () => {
    expect(formatDateID(null)).toBe('')
    expect(formatDateID(undefined)).toBe('')
    expect(formatDateID('')).toBe('')
    expect(formatDateID('not a date')).toBe('')
  })
})

describe('currencyOptions', () => {
  const listed = [
    { currency: 'IDR', count: 8093 },
    { currency: 'USD', count: 272 },
  ]

  it('always offers the "all" escape hatch and the server counts', () => {
    expect(currencyOptions(listed)).toEqual([
      { value: '', label: 'Semua mata uang' },
      { value: 'IDR', label: 'IDR — Rupiah (8093)' },
      { value: 'USD', label: 'USD — Dolar AS ($) (272)' },
    ])
  })

  it('keeps a filter the server stopped offering, so it can still be seen and cleared', () => {
    // A company with no USD figure drops USD from the list the server returns.
    // Without this the <select> would hold a value absent from its own options
    // and the browser would render it as "Semua mata uang", leaving the reader
    // looking at a filtered table with no sign of a filter.
    const options = currencyOptions([{ currency: 'IDR', count: 80 }], 'USD')
    expect(options.map((o) => o.value)).toEqual(['', 'IDR', 'USD'])
    expect(options.at(-1)?.label).toBe('USD — Dolar AS ($) (0)')
  })

  it('reports the real count when the filter is still listed', () => {
    expect(currencyOptions(listed, 'USD').filter((o) => o.value === 'USD')).toHaveLength(1)
    expect(currencyOptions(listed, 'USD').at(-1)?.label).toBe('USD — Dolar AS ($) (272)')
  })

  it('labels an empty currency as undetected rather than dropping it', () => {
    const options = currencyOptions([{ currency: 'IDR', count: 5 }], 'none')
    expect(options.at(-1)).toEqual({ value: 'none', label: 'Tidak terdeteksi (0)' })
  })

  it('adds nothing when no filter is set', () => {
    expect(currencyOptions(listed, '')).toEqual(currencyOptions(listed))
    expect(currencyOptions(undefined)).toEqual([{ value: '', label: 'Semua mata uang' }])
  })
})