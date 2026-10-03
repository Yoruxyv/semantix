import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

import type {
  AppRouteDefinition,
  IndexRouteDefinition,
  PathRouteDefinition,
} from './types';

interface LazyNamedPage {
  component: LazyExoticComponent<ComponentType>;
  preload: () => Promise<void>;
}

function lazyNamedPage<
  TExportName extends string,
  TModule extends Record<TExportName, ComponentType>,
>(importer: () => Promise<TModule>, exportName: TExportName): LazyNamedPage {
  let moduleRequest: Promise<TModule> | null = null;

  function loadModule(): Promise<TModule> {
    moduleRequest ??= importer().catch((error: unknown) => {
      moduleRequest = null;
      throw error;
    });

    return moduleRequest;
  }

  return {
    component: lazy(async () => {
      const module = await loadModule();

      return {
        default: module[exportName],
      };
    }),
    preload: async () => {
      await loadModule();
    },
  };
}

export function defineLazyIndexRoute<
  TExportName extends string,
  TModule extends Record<TExportName, ComponentType>,
>(
  key: string,
  importer: () => Promise<TModule>,
  exportName: TExportName,
): IndexRouteDefinition {
  const page = lazyNamedPage(importer, exportName);

  return {
    key,
    index: true,
    component: page.component,
    preload: page.preload,
  };
}

export function defineLazyPathRoute<
  TExportName extends string,
  TModule extends Record<TExportName, ComponentType>,
>(
  key: string,
  path: string,
  importer: () => Promise<TModule>,
  exportName: TExportName,
  children?: AppRouteDefinition[],
): PathRouteDefinition {
  const page = lazyNamedPage(importer, exportName);

  return {
    key,
    path,
    component: page.component,
    preload: page.preload,
    ...(children?.length ? { children } : {}),
  };
}
