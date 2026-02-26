import './styles/main.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import { App } from './App';

const app = new App('app');
app.init().catch(console.error);
