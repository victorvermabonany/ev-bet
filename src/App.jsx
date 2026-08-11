import { BrowserRouter, Route, Routes } from 'react-router-dom'

import Home from './pages/Home.jsx'
import Signup from './pages/Signup.jsx'
import Welcome from './pages/Welcome.jsx'
import Admin from './pages/Admin.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/welcome" element={<Welcome />} />
        <Route path="/admin" element={<Admin />} />
      </Routes>
    </BrowserRouter>
  )
}
