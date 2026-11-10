type FilterBarProps = { inicio: string; fim: string; onInicioChange: (value: string) => void; onFimChange: (value: string) => void; onRefresh: () => void };

export function FilterBar({ inicio, fim, onInicioChange, onFimChange, onRefresh }: FilterBarProps) {
  return <div className="filter" aria-label="Filtros do dashboard"><label htmlFor="inicio">De</label><input id="inicio" type="month" value={inicio} onChange={(event) => onInicioChange(event.target.value)} /><label htmlFor="fim">até</label><input id="fim" type="month" value={fim} onChange={(event) => onFimChange(event.target.value)} /><button className="refresh" type="button" onClick={onRefresh}>↻ Atualizar</button><span className="demo">Novo Caged · sem ajuste</span></div>;
}
