import { useEffect } from 'react';
import { useDispatch, useStore } from '../store';

export function Toast() {
  const toast = useStore().ui.toast;
  const dispatch = useDispatch();
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => dispatch({ type: 'ui', patch: { toast: null } }), 2200);
    return () => clearTimeout(id);
  }, [toast, dispatch]);
  if (!toast) return null;
  return (
    <div className="toast" role="status">
      {toast.text}
    </div>
  );
}
