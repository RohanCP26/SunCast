import React, { useEffect, useRef, useState } from 'react';
import SunsetPredictor from './sunsetPredictor';
import Social from './Social';
import './App.css';

const SWIPE_SLOP = 12;

function App() {
  const [index, setIndex] = useState(0);
  const [eveningDraft, setEveningDraft] = useState(null);
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [heights, setHeights] = useState([0, 0]);
  const viewportRef = useRef(null);
  const forecastRef = useRef(null);
  const socialRef = useRef(null);
  const gesture = useRef(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    const nodes = [forecastRef.current, socialRef.current];
    const measure = () => {
      setHeights(nodes.map((node) => node?.offsetHeight || 0));
    };
    measure();
    const observer = new ResizeObserver(measure);
    nodes.forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, []);

  const goTo = (next) => {
    setDragging(false);
    setDragX(0);
    setIndex(next);
  };

  const onPointerDown = (event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (event.target.closest('.rate-bar, input, textarea, select, a')) return;
    gesture.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      lastX: event.clientX,
      lastT: event.timeStamp,
      vx: 0,
      active: false,
    };
  };

  const onPointerMove = (event) => {
    const current = gesture.current;
    if (!current || event.pointerId !== current.id) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (!current.active) {
      if (Math.abs(dx) < SWIPE_SLOP && Math.abs(dy) < SWIPE_SLOP) return;
      if (Math.abs(dy) > Math.abs(dx)) {
        gesture.current = null;
        return;
      }
      current.active = true;
      suppressClick.current = true;
      setDragging(true);
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch (err) {
        // Capture is optional; the swipe still follows the pointer.
      }
    }
    const dt = event.timeStamp - current.lastT;
    if (dt > 0) current.vx = (event.clientX - current.lastX) / dt;
    current.lastX = event.clientX;
    current.lastT = event.timeStamp;
    let next = dx;
    if ((index === 0 && next > 0) || (index === 1 && next < 0)) next *= 0.28;
    setDragX(next);
  };

  const endGesture = (event) => {
    const current = gesture.current;
    if (!current || event.pointerId !== current.id) return;
    gesture.current = null;
    if (!current.active) return;
    window.setTimeout(() => {
      suppressClick.current = false;
    }, 350);
    const dx = event.clientX - current.x;
    const width = viewportRef.current?.clientWidth || window.innerWidth;
    const fling = current.vx < -0.45 || current.vx > 0.45;
    const passed = Math.abs(dx) > Math.min(72, width * 0.18) || fling;
    setDragging(false);
    setDragX(0);
    if (passed && dx < 0 && index === 0) setIndex(1);
    else if (passed && dx > 0 && index === 1) setIndex(0);
  };

  const onClickCapture = (event) => {
    if (!suppressClick.current) return;
    suppressClick.current = false;
    event.preventDefault();
    event.stopPropagation();
  };

  const width = viewportRef.current?.clientWidth || 1;
  const travel = index === 0
    ? Math.min(1, Math.max(0, -dragX / width))
    : Math.min(1, Math.max(0, dragX / width));
  const fromHeight = heights[index] || 0;
  const toHeight = heights[index === 0 ? 1 : 0] || fromHeight;
  const viewportHeight = dragging
    ? fromHeight + (toHeight - fromHeight) * travel
    : fromHeight;

  return (
    <div className="app">
      <nav className="app-nav" aria-label="Primary">
        <div className="nav-brand">
          <img src="/suncast-logo.png" alt="" />
          <span>SunCast</span>
        </div>
        <div className="nav-tabs">
          <button
            type="button"
            className={index === 0 ? 'active' : ''}
            onClick={() => goTo(0)}
          >
            Forecast
          </button>
          <button
            type="button"
            className={index === 1 ? 'active' : ''}
            onClick={() => goTo(1)}
          >
            Social
          </button>
        </div>
      </nav>

      <div
        className={`page-viewport${dragging ? ' is-dragging' : ''}`}
        ref={viewportRef}
        style={viewportHeight ? { height: viewportHeight } : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onClickCapture={onClickCapture}
      >
        <div
          className={`page-track${dragging ? ' is-dragging' : ''}`}
          style={{ marginLeft: `calc(${-index * 100}% + ${dragging ? dragX : 0}px)` }}
        >
          <div className="page-pane" ref={forecastRef} inert={index !== 0} aria-hidden={index !== 0}>
            <SunsetPredictor
              onShareEvening={(draft) => {
                setEveningDraft(draft);
                goTo(1);
              }}
            />
          </div>
          <div className="page-pane" ref={socialRef} inert={index !== 1} aria-hidden={index !== 1}>
            <Social
              eveningDraft={eveningDraft}
              onEveningDraftUsed={() => setEveningDraft(null)}
            />
          </div>
        </div>
      </div>

      <footer className="app-footer">
        <img src="/suncast-logo.png" alt="SunCast" className="footer-logo" />
        <p className="footer-brand">SunCast</p>
        <p className="footer-note">Weather via Open-Meteo · Scored with gradient boosting</p>
        <p className="footer-author">Author: Rohan Paranjape</p>
      </footer>
    </div>
  );
}

export default App;
