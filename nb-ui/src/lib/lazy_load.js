let plotlyPromise = null;
let vegaPromise = null;

export function loadPlotly() {
    if (plotlyPromise) return plotlyPromise;
    
    plotlyPromise = new Promise((resolve, reject) => {
        if (window.Plotly) {
            resolve(window.Plotly);
            return;
        }
        const script = document.createElement('script');
        script.src = "https://cdn.plot.ly/plotly-2.24.1.min.js";
        script.onload = () => resolve(window.Plotly);
        script.onerror = (e) => {
            plotlyPromise = null;
            reject(e);
        };
        document.head.appendChild(script);
    });
    return plotlyPromise;
}

export function loadVega() {
    if (vegaPromise) return vegaPromise;
    
    vegaPromise = new Promise((resolve, reject) => {
        if (window.vegaEmbed) {
            resolve(window.vegaEmbed);
            return;
        }
        
        // Load vega, vega-lite, then vega-embed sequentially
        const s1 = document.createElement('script');
        s1.src = "https://cdn.jsdelivr.net/npm/vega@5";
        s1.onload = () => {
            const s2 = document.createElement('script');
            s2.src = "https://cdn.jsdelivr.net/npm/vega-lite@5";
            s2.onload = () => {
                const s3 = document.createElement('script');
                s3.src = "https://cdn.jsdelivr.net/npm/vega-embed@6";
                s3.onload = () => resolve(window.vegaEmbed);
                s3.onerror = (e) => {
                    vegaPromise = null;
                    reject(e);
                };
                document.head.appendChild(s3);
            };
            s2.onerror = (e) => {
                vegaPromise = null;
                reject(e);
            };
            document.head.appendChild(s2);
        };
        s1.onerror = (e) => {
            vegaPromise = null;
            reject(e);
        };
        document.head.appendChild(s1);
    });
    return vegaPromise;
}
