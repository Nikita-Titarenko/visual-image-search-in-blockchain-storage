import { PUBLIC_ENV } from './public-env';

export interface ContractAddresses {
  imageRegistry: string;
  licensingAndPayment: string;
  modelAndIndexAudit: string;
}

export interface NetworkConfig {
  chainId: number;
  chainName: string;
  rpcUrl: string;
  blockExplorerUrl: string;
  nativeCurrency: {
    name: string;
    symbol: string;
    decimals: number;
  };
}

export const POLYGON_AMOY_CONFIG: NetworkConfig = {
  chainId: 80002,
  chainName: 'Polygon Amoy',
  rpcUrl: PUBLIC_ENV.polygonAmoyRpcUrl,
  blockExplorerUrl: 'https://amoy.polygonscan.com',
  nativeCurrency: {
    name: 'MATIC',
    symbol: 'MATIC',
    decimals: 18,
  },
};

export const DEFAULT_CONTRACT_ADDRESSES: ContractAddresses = {
  imageRegistry: '0x21935960B1e9400a56CeB9b05E94a805D4c6235a',
  licensingAndPayment: '0xc9Af267aF4e9740c95187A2b373A0c399C20f030',
  modelAndIndexAudit: '0x40915402424b6c105327a3Dc53a920dff0b1d94a',
};