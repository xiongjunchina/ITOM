export interface LocalizedReleaseNotes {
  title: string;
  summary: string;
  highlights: string[];
  fixes: string[];
  known_limits: string[];
}

export interface PublicSoftwareRelease {
  schema_version: number;
  product: {
    code: string;
    name_zh: string;
    name_en: string;
    edition_zh: string;
    edition_en: string;
  };
  release: {
    version: string;
    channel: 'stable' | 'candidate' | 'development';
    status: 'released' | 'candidate' | 'development' | 'retired';
    release_date: string;
  };
  notes: { zh: LocalizedReleaseNotes; en: LocalizedReleaseNotes };
}

/** Frontend build identity embedded from the same Git-controlled release manifest as the backend. */
export const buildRelease = __ITOM_RELEASE__;
