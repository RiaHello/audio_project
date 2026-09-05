export default function CitySelect({ value, onChange }) {
  return (
    <label className="city-select">
      <span className="label">页面城市</span>
      <input
        type="text"
        name="city"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
        aria-label="页面城市"
      />
    </label>
  );
}
