import type { ComponentType, LazyExoticComponent } from 'react';

type RouteComponent = ComponentType | LazyExoticComponent<ComponentType>;

interface BaseRouteDefinition {
  component: RouteComponent;
  key: string;
  preload?: () => Promise<void>;
}

export interface IndexRouteDefinition extends BaseRouteDefinition {
  children?: never;
  index: true;
  path?: never;
}

export interface PathRouteDefinition extends BaseRouteDefinition {
  children?: AppRouteDefinition[];
  index?: false;
  path: string;
}

export type AppRouteDefinition = IndexRouteDefinition | PathRouteDefinition;
